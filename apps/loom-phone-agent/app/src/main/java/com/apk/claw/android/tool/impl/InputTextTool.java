package com.apk.claw.android.tool.impl;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityNodeInfo;

import com.apk.claw.android.ClawApplication;
import com.apk.claw.android.R;
import com.apk.claw.android.comment.UiBounds;
import com.apk.claw.android.service.ClawAccessibilityService;
import com.apk.claw.android.tool.BaseTool;
import com.apk.claw.android.tool.ToolParameter;
import com.apk.claw.android.tool.ToolResult;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

public class InputTextTool extends BaseTool {

    @Override
    public String getName() {
        return "input_text";
    }

    @Override
    public String getDisplayName() {
        return ClawApplication.Companion.getInstance().getString(R.string.tool_name_input_text);
    }

    @Override
    public String getDescriptionEN() {
        return "Input text into a focused or uniquely targeted editable field. "
                + "Legacy calls may focus a field first. For reliable workflows, provide package_name "
                + "and resource_id, text_hint, or bounds_hint. Targeted calls fail when the field is "
                + "missing or ambiguous instead of writing to the first editable field.";
    }

    @Override
    public String getDescriptionCN() {
        return "\u5411\u5df2\u805a\u7126\u6216\u552f\u4e00\u5339\u914d\u7684\u6587\u672c\u6846\u8f93\u5165\u5185\u5bb9\u3002"
                + "\u7a33\u5b9a\u5de5\u4f5c\u6d41\u5e94\u4f20 package_name \u4ee5\u53ca resource_id\u3001text_hint \u6216 bounds_hint\u3002"
                + "\u76ee\u6807\u4e0d\u5b58\u5728\u6216\u4e0d\u552f\u4e00\u65f6\u4f1a\u660e\u786e\u5931\u8d25\uff0c\u4e0d\u4f1a\u8bef\u5199\u5176\u4ed6\u8f93\u5165\u6846\u3002";
    }

    @Override
    public List<ToolParameter> getParameters() {
        return Arrays.asList(
                new ToolParameter("text", "string", "The text to input", true),
                new ToolParameter("clear_first", "boolean", "Whether to clear existing text before input (default true)", false),
                new ToolParameter("package_name", "string", "Optional exact package for a targeted input", false),
                new ToolParameter("resource_id", "string", "Optional exact accessibility resource ID", false),
                new ToolParameter("text_hint", "string", "Optional visible text or description hint", false),
                new ToolParameter("bounds_hint", "object", "Optional bounds object with left, top, right, bottom", false),
                new ToolParameter("require_focused", "boolean", "Require the resolved input to already be focused", false),
                new ToolParameter("expected_existing_text", "string", "Optional exact current text precondition", false)
        );
    }

    @Override
    public ToolResult execute(Map<String, Object> params) {
        ClawAccessibilityService service = ClawAccessibilityService.getInstance();
        if (service == null) {
            return ToolResult.error("accessibility_unavailable: Accessibility service is not running");
        }

        String text = requireString(params, "text");
        boolean clearFirst = optionalBoolean(params, "clear_first", true);
        boolean targetedMode = hasTargetContract(params);
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        if (root == null) {
            return ToolResult.error("screen_tree_unavailable: Active accessibility root is unavailable");
        }

        List<AccessibilityNodeInfo> candidateNodes = new ArrayList<>();
        AccessibilityNodeInfo targetNode = null;
        try {
            if (targetedMode) {
                collectEditableNodes(root, candidateNodes);
                List<TextInputNodeSnapshot> snapshots = snapshot(candidateNodes);
                TextInputTargetSpec spec = targetSpec(params);
                TextInputResolution resolution = TargetedTextInputResolver.INSTANCE.resolve(spec, snapshots);
                if (resolution instanceof TextInputResolution.NotFound) {
                    return ToolResult.error("comment_composer_unreachable: no editable target matched the supplied contract");
                }
                if (resolution instanceof TextInputResolution.Ambiguous) {
                    return ToolResult.error("comment_composer_ambiguous: multiple editable targets matched the supplied contract");
                }
                int index = ((TextInputResolution.Unique) resolution).getNode().getIndex();
                if (index < 0 || index >= candidateNodes.size()) {
                    return ToolResult.error("comment_composer_unreachable: resolved target is no longer available");
                }
                targetNode = candidateNodes.get(index);
            } else {
                targetNode = findFocusedEditText(root);
            }

            if (targetNode == null) {
                return ToolResult.error("No target text field found");
            }

            targetNode.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
            targetNode.performAction(AccessibilityNodeInfo.ACTION_CLICK);

            if (clearFirst) {
                clearNodeText(targetNode);
            }

            if (setTextDirectly(targetNode, text, clearFirst)) {
                return ToolResult.success(clearFirst ? "Input text: " + text : "Appended text: " + text);
            }

            if (!setClipboardText(service, text)) {
                return ToolResult.error("Failed to set clipboard text");
            }

            prepareForPaste(targetNode, clearFirst);
            if (targetNode.performAction(AccessibilityNodeInfo.ACTION_PASTE)) {
                return ToolResult.success(clearFirst
                        ? "Input text (via paste): " + text
                        : "Appended text (via paste): " + text);
            }
            return ToolResult.error("Failed to input text, both ACTION_SET_TEXT and clipboard paste failed");
        } finally {
            recycleDistinct(root, targetNode, candidateNodes);
        }
    }

    private boolean hasTargetContract(Map<String, Object> params) {
        return hasNonBlank(params, "package_name")
                || hasNonBlank(params, "resource_id")
                || hasNonBlank(params, "text_hint")
                || params.get("bounds_hint") != null
                || optionalBoolean(params, "require_focused", false)
                || params.containsKey("expected_existing_text");
    }

    private boolean hasNonBlank(Map<String, Object> params, String key) {
        Object value = params.get(key);
        return value != null && !value.toString().trim().isEmpty();
    }

    private TextInputTargetSpec targetSpec(Map<String, Object> params) {
        String expected = params.containsKey("expected_existing_text")
                ? optionalString(params, "expected_existing_text", "")
                : null;
        return new TextInputTargetSpec(
                optionalString(params, "package_name", ""),
                optionalString(params, "resource_id", ""),
                optionalString(params, "text_hint", ""),
                parseBounds(params.get("bounds_hint")),
                optionalBoolean(params, "require_focused", false),
                expected
        );
    }

    private UiBounds parseBounds(Object value) {
        if (!(value instanceof Map)) return null;
        Map<?, ?> map = (Map<?, ?>) value;
        Integer left = mapInt(map, "left");
        Integer top = mapInt(map, "top");
        Integer right = mapInt(map, "right");
        Integer bottom = mapInt(map, "bottom");
        if (left == null || top == null || right == null || bottom == null) return null;
        if (right <= left || bottom <= top) return null;
        return new UiBounds(left, top, right, bottom);
    }

    private Integer mapInt(Map<?, ?> map, String key) {
        Object value = map.get(key);
        if (value instanceof Number) return ((Number) value).intValue();
        if (value == null) return null;
        try {
            return Integer.parseInt(value.toString());
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private boolean collectEditableNodes(
            AccessibilityNodeInfo node,
            List<AccessibilityNodeInfo> output
    ) {
        if (node == null) return false;
        if (node.isVisibleToUser() && node.isEnabled() && node.isEditable()) {
            output.add(node);
            return true;
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child == null) continue;
            boolean retained = collectEditableNodes(child, output);
            if (!retained) child.recycle();
        }
        return false;
    }

    private List<TextInputNodeSnapshot> snapshot(List<AccessibilityNodeInfo> nodes) {
        List<TextInputNodeSnapshot> snapshots = new ArrayList<>(nodes.size());
        for (int i = 0; i < nodes.size(); i++) {
            AccessibilityNodeInfo node = nodes.get(i);
            Rect rect = new Rect();
            node.getBoundsInScreen(rect);
            snapshots.add(new TextInputNodeSnapshot(
                    i,
                    value(node.getPackageName()),
                    value(node.getViewIdResourceName()),
                    value(node.getClassName()),
                    value(node.getText()),
                    value(node.getContentDescription()),
                    new UiBounds(rect.left, rect.top, rect.right, rect.bottom),
                    node.isEditable(),
                    node.isFocused(),
                    node.isVisibleToUser(),
                    node.isEnabled()
            ));
        }
        return snapshots;
    }

    private String value(CharSequence value) {
        return value == null ? "" : value.toString();
    }

    private boolean setTextDirectly(AccessibilityNodeInfo targetNode, String text, boolean clearFirst) {
        String newText = text;
        if (!clearFirst) {
            CharSequence existing = targetNode.getText();
            newText = (existing != null ? existing.toString() : "") + text;
        }
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, newText);
        return targetNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }

    private void prepareForPaste(AccessibilityNodeInfo targetNode, boolean clearFirst) {
        if (clearFirst) {
            clearNodeText(targetNode);
            return;
        }
        CharSequence existing = targetNode.getText();
        int end = existing != null ? existing.length() : 0;
        Bundle cursorArgs = new Bundle();
        cursorArgs.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, end);
        cursorArgs.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, end);
        targetNode.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, cursorArgs);
    }

    private void clearNodeText(AccessibilityNodeInfo node) {
        Bundle selectAllArgs = new Bundle();
        selectAllArgs.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, 0);
        selectAllArgs.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, Integer.MAX_VALUE);
        node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, selectAllArgs);

        Bundle clearArgs = new Bundle();
        clearArgs.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "");
        node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, clearArgs);
    }

    private boolean setClipboardText(Context context, String text) {
        CountDownLatch latch = new CountDownLatch(1);
        boolean[] result = {false};
        new Handler(Looper.getMainLooper()).post(() -> {
            try {
                ClipboardManager clipboard =
                        (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
                if (clipboard != null) {
                    clipboard.setPrimaryClip(ClipData.newPlainText("input_text", text));
                    result[0] = true;
                }
            } catch (Exception ignored) {
            }
            latch.countDown();
        });

        try {
            latch.await(2, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
        return result[0];
    }

    private AccessibilityNodeInfo findFocusedEditText(AccessibilityNodeInfo root) {
        if (root == null) return null;
        AccessibilityNodeInfo focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (focused != null && focused.isEditable()) {
            return focused;
        }
        if (focused != null) focused.recycle();
        return findFirstEditable(root);
    }

    private AccessibilityNodeInfo findFirstEditable(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isEditable()) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child == null) continue;
            AccessibilityNodeInfo result = findFirstEditable(child);
            if (result != null) {
                if (result != child) child.recycle();
                return result;
            }
            child.recycle();
        }
        return null;
    }

    private void recycleDistinct(
            AccessibilityNodeInfo root,
            AccessibilityNodeInfo target,
            List<AccessibilityNodeInfo> candidates
    ) {
        for (AccessibilityNodeInfo candidate : candidates) {
            if (candidate != null) candidate.recycle();
        }
        if (target != null && !candidates.contains(target) && target != root) {
            target.recycle();
        }
        if (root != null && !candidates.contains(root)) {
            root.recycle();
        }
    }
}
