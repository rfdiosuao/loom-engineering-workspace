package com.apk.claw.android.service;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.res.Configuration;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.util.DisplayMetrics;
import com.apk.claw.android.server.ConfigServerManager;
import com.apk.claw.android.utils.XLog;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Core accessibility service that provides all device interaction capabilities.
 * Singleton-pattern: the running instance is accessible via {@link #getInstance()}.
 */
public class ClawAccessibilityService extends AccessibilityService {

    private static final String TAG = "ClawA11yService";
    private static final long SCREENSHOT_MIN_INTERVAL_MS = 650L;
    private static final long SCREENSHOT_CACHE_TTL_MS = 900L;
    private static final long SCREENSHOT_STALE_FALLBACK_MS = 3000L;
    private static volatile ClawAccessibilityService instance;
    private volatile String lastForegroundPackageName;
    private volatile long lastForegroundPackageAt;
    private final Object screenshotLock = new Object();
    private Bitmap lastScreenshotBitmap;
    private long lastScreenshotAt;

    public static ClawAccessibilityService getInstance() {
        return instance;
    }

    public static boolean isRunning() {
        return instance != null;
    }

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        ForegroundService.Companion.start(this);
        KeepAliveJobService.Companion.schedule(this);
        ConfigServerManager.INSTANCE.autoStartIfNeeded(this);
        XLog.i(TAG, "Accessibility service connected");
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event != null && event.getPackageName() != null) {
            lastForegroundPackageName = event.getPackageName().toString();
            lastForegroundPackageAt = System.currentTimeMillis();
        }
    }

    @Override
    public void onInterrupt() {
        XLog.w(TAG, "Accessibility service interrupted");
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        instance = null;
        recycleLastScreenshot();
        XLog.i(TAG, "Accessibility service destroyed");
    }

    // ======================== Gesture Operations ========================

    /**
     * Performs a tap at the given screen coordinates.
     */
    public boolean performTap(int x, int y) {
        return performTap(x, y, 100);
    }

    public boolean performTap(int x, int y, long durationMs) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, durationMs);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(stroke)
                .build();
        return dispatchGestureSync(gesture);
    }

    /**
     * Revalidates an Agent tap against the live accessibility tree. Structured UI targets use
     * ACTION_CLICK; unstructured surfaces such as canvases keep exact coordinate behavior.
     */
    public boolean performNodeAwareTap(int x, int y, long durationMs) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return performTap(x, y, durationMs);
        }

        List<AccessibilityNodeInfo> clickableNodes = new ArrayList<>();
        List<NodeAwareTapSelector.Candidate> candidates = new ArrayList<>();
        try {
            collectNodeAwareTapCandidates(root, 0, clickableNodes, candidates);
            Rect rootBounds = new Rect();
            root.getBoundsInScreen(rootBounds);
            long rootArea = Math.max(0L, (long) rootBounds.width() * rootBounds.height());
            int selectedIndex = NodeAwareTapSelector.selectIndex(candidates, x, y, rootArea);
            if (selectedIndex >= 0 && selectedIndex < clickableNodes.size()) {
                AccessibilityNodeInfo selected = clickableNodes.get(selectedIndex);
                if (selected.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    XLog.d(TAG, "Node-aware tap resolved (" + x + "," + y + ") to "
                            + selected.getClassName());
                    return true;
                }
            }
        } catch (RuntimeException e) {
            XLog.w(TAG, "Node-aware tap fallback: " + e.getMessage());
        } finally {
            recycleNodes(clickableNodes);
            root.recycle();
        }
        return performTap(x, y, durationMs);
    }

    private void collectNodeAwareTapCandidates(
            AccessibilityNodeInfo node,
            int depth,
            List<AccessibilityNodeInfo> clickableNodes,
            List<NodeAwareTapSelector.Candidate> candidates
    ) {
        if (node == null) return;
        if (node.isClickable()) {
            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            if (!bounds.isEmpty()) {
                int index = clickableNodes.size();
                clickableNodes.add(AccessibilityNodeInfo.obtain(node));
                candidates.add(new NodeAwareTapSelector.Candidate(
                        index,
                        bounds.left,
                        bounds.top,
                        bounds.right,
                        bounds.bottom,
                        depth,
                        node.isEnabled(),
                        node.isVisibleToUser(),
                        hasSemanticClickIdentity(node)
                ));
            }
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                try {
                    collectNodeAwareTapCandidates(child, depth + 1, clickableNodes, candidates);
                } finally {
                    child.recycle();
                }
            }
        }
    }

    private boolean hasSemanticClickIdentity(AccessibilityNodeInfo node) {
        if (hasText(node.getText()) || hasText(node.getContentDescription())
                || hasText(node.getViewIdResourceName()) || node.isCheckable()) {
            return true;
        }
        CharSequence className = node.getClassName();
        if (className == null) return false;
        String value = className.toString();
        return value.endsWith("Button") || value.endsWith("CheckBox") || value.endsWith("Switch");
    }

    private boolean hasText(CharSequence value) {
        return value != null && !value.toString().trim().isEmpty();
    }

    /**
     * Performs a long press at the given screen coordinates.
     */
    public boolean performLongPress(int x, int y, long durationMs) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, durationMs);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(stroke)
                .build();
        return dispatchGestureSync(gesture);
    }

    /**
     * Performs a swipe gesture from (startX, startY) to (endX, endY).
     */
    public boolean performSwipe(int startX, int startY, int endX, int endY, long durationMs) {
        Path path = new Path();
        path.moveTo(startX, startY);
        path.lineTo(endX, endY);
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, durationMs);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(stroke)
                .build();
        return dispatchGestureSync(gesture);
    }

    /**
     * Performs a real drag gesture: hold at the start point, then move to the end point.
     */
    public boolean performDrag(int startX, int startY, int endX, int endY, long holdMs, long durationMs) {
        Path holdPath = new Path();
        holdPath.moveTo(startX, startY);
        GestureDescription.StrokeDescription holdStroke =
                new GestureDescription.StrokeDescription(holdPath, 0, holdMs, true);

        Path dragPath = new Path();
        dragPath.moveTo(startX, startY);
        dragPath.lineTo(endX, endY);
        GestureDescription.StrokeDescription dragStroke =
                holdStroke.continueStroke(dragPath, holdMs, durationMs, false);

        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(holdStroke)
                .addStroke(dragStroke)
                .build();
        return dispatchGestureSync(gesture);
    }

    /**
     * Dispatches a gesture and waits for it to complete synchronously.
     */
    private boolean dispatchGestureSync(GestureDescription gesture) {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicBoolean result = new AtomicBoolean(false);

        boolean dispatched = dispatchGesture(gesture, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gestureDescription) {
                result.set(true);
                latch.countDown();
            }

            @Override
            public void onCancelled(GestureDescription gestureDescription) {
                result.set(false);
                latch.countDown();
            }
        }, null);

        if (!dispatched) {
            return false;
        }

        try {
            latch.await(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
        return result.get();
    }

    // ======================== Node Operations ========================

    /**
     * Finds all nodes matching the given text.
     */
    public List<AccessibilityNodeInfo> findNodesByText(String text) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return new ArrayList<>();
        }
        List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByText(text);
        return nodes != null ? nodes : new ArrayList<>();
    }

    /**
     * Finds all nodes matching the given view ID (e.g. "com.example:id/button").
     */
    public List<AccessibilityNodeInfo> findNodesById(String viewId) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return new ArrayList<>();
        }
        List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId(viewId);
        return nodes != null ? nodes : new ArrayList<>();
    }

    /**
     * Finds all visible nodes matching the given content description.
     */
    public List<AccessibilityNodeInfo> findNodesByDescription(String description) {
        List<AccessibilityNodeInfo> results = new ArrayList<>();
        if (description == null || description.trim().isEmpty()) {
            return results;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return results;
        }
        try {
            collectNodesByDescription(root, description.trim().toLowerCase(Locale.US), results);
        } finally {
            root.recycle();
        }
        return results;
    }

    private void collectNodesByDescription(
            AccessibilityNodeInfo node,
            String description,
            List<AccessibilityNodeInfo> results
    ) {
        if (node == null) {
            return;
        }
        CharSequence current = node.getContentDescription();
        if (node.isVisibleToUser() && current != null
                && current.toString().toLowerCase(Locale.US).contains(description)) {
            results.add(AccessibilityNodeInfo.obtain(node));
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                try {
                    collectNodesByDescription(child, description, results);
                } finally {
                    child.recycle();
                }
            }
        }
    }

    /**
     * Clicks on a node.
     */
    public boolean clickNode(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }
        if (node.isClickable()) {
            return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        }
        // Try clicking the parent if the node itself is not clickable
        AccessibilityNodeInfo parent = node.getParent();
        while (parent != null) {
            if (parent.isClickable()) {
                return parent.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            }
            parent = parent.getParent();
        }
        // Fallback: tap at center of node bounds
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        return performTap(bounds.centerX(), bounds.centerY());
    }

    /**
     * Sets text on a node (for EditText fields).
     */
    public boolean setNodeText(AccessibilityNodeInfo node, String text) {
        if (node == null) {
            return false;
        }
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }

    /**
     * Collects a tree representation of the current screen for AI analysis.
     */
    public String getScreenTree() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        buildNodeTree(root, sb, 0);
        return sb.toString();
    }

    /**
     * Collects a FULL tree representation of the current screen (debug only).
     * Includes ALL nodes with all properties, no filtering.
     * Useful for comparing with the filtered version to debug AI behavior.
     */
    public String getScreenTreeFull() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        buildNodeTreeFull(root, sb, 0);
        return sb.toString();
    }

    /**
     * Collects a structured screen tree for desktop/agent clients.
     * The result is a flat node list with parentId/depth so clients can render
     * bounds overlays without parsing the legacy text tree.
     */
    public JsonObject getScreenTreeJson() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return null;
        }

        DisplayMetrics metrics = getResources().getDisplayMetrics();
        JsonObject screen = new JsonObject();
        screen.addProperty("width", metrics.widthPixels);
        screen.addProperty("height", metrics.heightPixels);
        screen.addProperty(
                "orientation",
                getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE
                        ? "landscape"
                        : "portrait"
        );
        // 当前前台 App 的包名 + 名称：让 Agent 不必去读信息流内容，靠这个就能确认
        // 「现在在哪个 App」（小红书等信息流型 App 可访问性文本少时尤其有用）。
        CharSequence rootPkg = root.getPackageName();
        String currentPackage = rootPkg != null && rootPkg.length() > 0
                ? rootPkg.toString()
                : (lastForegroundPackageName != null ? lastForegroundPackageName : "");
        if (!currentPackage.isEmpty()) {
            screen.addProperty("currentPackage", currentPackage);
            String appLabel = resolveAppLabel(currentPackage);
            if (appLabel != null && !appLabel.isEmpty()) {
                screen.addProperty("currentApp", appLabel);
            }
        }

        JsonArray nodes = new JsonArray();
        buildNodeJsonTree(root, nodes, null, 0, new int[]{0});

        JsonObject data = new JsonObject();
        data.add("screen", screen);
        data.add("nodes", nodes);
        return data;
    }

    /** 包名 -> 用户可读的 App 名称（取不到就返回 null）。 */
    private String resolveAppLabel(String packageName) {
        if (packageName == null || packageName.isEmpty()) {
            return null;
        }
        try {
            android.content.pm.PackageManager pm = getPackageManager();
            CharSequence label = pm.getApplicationLabel(pm.getApplicationInfo(packageName, 0));
            return label == null ? null : label.toString();
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * Best-effort foreground package probe.
     * Prefer the active root package; fall back to the latest accessibility event.
     */
    public String getCurrentPackageName() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root != null) {
            try {
                CharSequence packageName = root.getPackageName();
                if (packageName != null && packageName.length() > 0) {
                    lastForegroundPackageName = packageName.toString();
                    lastForegroundPackageAt = System.currentTimeMillis();
                    return lastForegroundPackageName;
                }
            } finally {
                root.recycle();
            }
        }
        return lastForegroundPackageName;
    }

    public long getCurrentPackageObservedAt() {
        return lastForegroundPackageAt;
    }

    private void buildNodeTree(AccessibilityNodeInfo node, StringBuilder sb, int depth) {
        if (node == null) {
            return;
        }

        // 跳过不在屏幕可见区域内的节点（滚动容器中超出屏幕的元素）
        if (!node.isVisibleToUser()) {
            // 仍然遍历子节点，因为父节点不可见不代表所有子节点都不可见
            for (int i = 0; i < node.getChildCount(); i++) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) {
                    buildNodeTree(child, sb, depth);
                    child.recycle();
                }
            }
            return;
        }

        // 判断当前节点是否有"信息量"（有 text/desc/可交互/可滚动/可编辑/进度条/滑块）
        boolean hasText = node.getText() != null && node.getText().length() > 0;
        boolean hasDesc = node.getContentDescription() != null && node.getContentDescription().length() > 0;
        boolean isInteractive = node.isClickable() || node.isScrollable() || node.isEditable()
                || node.isCheckable() || node.isLongClickable();
        boolean isSlider = isSliderNode(node);
        CharSequence cn = node.getClassName();
        boolean isProgress = cn != null && cn.toString().contains("ProgressBar");
        boolean isMeaningful = hasText || hasDesc || isInteractive || isSlider || isProgress;

        if (isMeaningful) {
            String indent = "  ".repeat(depth);
            sb.append(indent);

            // 简化 className：只保留最后一段（如 android.widget.TextView → TextView）
            CharSequence className = node.getClassName();
            if (className != null) {
                String cls = className.toString();
                int dotIdx = cls.lastIndexOf('.');
                sb.append("[").append(dotIdx >= 0 ? cls.substring(dotIdx + 1) : cls).append("]");
            }

            if (hasText) {
                // 截断超长文本，避免输出爆炸
                CharSequence text = node.getText();
                if (text.length() > 100) {
                    sb.append(" text=\"").append(text.subSequence(0, 100)).append("...\"");
                } else {
                    sb.append(" text=\"").append(text).append("\"");
                }
            }
            if (hasDesc) {
                sb.append(" desc=\"").append(node.getContentDescription()).append("\"");
            }
            if (node.isClickable()) {
                sb.append(" [clickable]");
            }
            if (node.isLongClickable()) {
                sb.append(" [long-clickable]");
            }
            if (node.isScrollable()) {
                sb.append(" [scrollable]");
            }
            if (node.isEditable()) {
                sb.append(" [editable]");
            }
            if (node.isCheckable()) {
                sb.append(node.isChecked() ? " [checked]" : " [unchecked]");
            }
            if (!node.isEnabled()) {
                sb.append(" [disabled]");
            }
            if (node.isFocused()) {
                sb.append(" [focused]");
            }
            if (isProgress) {
                sb.append(" [loading]");
            }

            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            sb.append(" bounds=").append(bounds.toShortString());

            sb.append("\n");
        }

        // 子节点层级：如果当前节点被跳过（非 meaningful），子节点保持同层级，不增加 depth
        int childDepth = isMeaningful ? depth + 1 : depth;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                buildNodeTree(child, sb, childDepth);
                child.recycle();
            }
        }
    }

    private void buildNodeJsonTree(
            AccessibilityNodeInfo node,
            JsonArray nodes,
            String parentId,
            int depth,
            int[] counter
    ) {
        if (node == null) {
            return;
        }

        boolean visible = node.isVisibleToUser();
        boolean hasText = node.getText() != null && node.getText().length() > 0;
        boolean hasDesc = node.getContentDescription() != null && node.getContentDescription().length() > 0;
        boolean isInteractive = node.isClickable() || node.isScrollable() || node.isEditable()
                || node.isCheckable() || node.isLongClickable();
        boolean isSlider = isSliderNode(node);
        CharSequence cn = node.getClassName();
        boolean isProgress = cn != null && cn.toString().contains("ProgressBar");
        boolean isMeaningful = visible && (hasText || hasDesc || isInteractive || isSlider || isProgress);

        String currentParentId = parentId;
        int childDepth = depth;
        if (isMeaningful) {
            String nodeId = "node-" + (++counter[0]);
            currentParentId = nodeId;
            childDepth = depth + 1;

            JsonObject item = new JsonObject();
            item.addProperty("id", nodeId);
            if (parentId != null) {
                item.addProperty("parentId", parentId);
            } else {
                item.add("parentId", JsonNull.INSTANCE);
            }
            item.addProperty("depth", depth);
            item.addProperty("className", simpleClassName(node.getClassName()));
            addNullableString(item, "text", truncate(node.getText(), 200));
            addNullableString(item, "description", truncate(node.getContentDescription(), 200));
            addNullableString(item, "resourceId", node.getViewIdResourceName());
            addNullableString(item, "packageName", node.getPackageName() == null ? null : node.getPackageName().toString());
            item.addProperty("clickable", node.isClickable());
            item.addProperty("longClickable", node.isLongClickable());
            item.addProperty("scrollable", node.isScrollable());
            item.addProperty("editable", node.isEditable());
            item.addProperty("checkable", node.isCheckable());
            item.addProperty("checked", node.isChecked());
            item.addProperty("enabled", node.isEnabled());
            item.addProperty("focused", node.isFocused());
            item.addProperty("selected", node.isSelected());
            item.addProperty("visible", visible);
            item.addProperty("slider", isSlider);
            item.addProperty("loading", isProgress);

            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            JsonObject boundsJson = new JsonObject();
            boundsJson.addProperty("left", bounds.left);
            boundsJson.addProperty("top", bounds.top);
            boundsJson.addProperty("right", bounds.right);
            boundsJson.addProperty("bottom", bounds.bottom);
            boundsJson.addProperty("width", bounds.width());
            boundsJson.addProperty("height", bounds.height());
            boundsJson.addProperty("centerX", bounds.centerX());
            boundsJson.addProperty("centerY", bounds.centerY());
            item.add("bounds", boundsJson);

            nodes.add(item);
        }

        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                buildNodeJsonTree(child, nodes, currentParentId, childDepth, counter);
                child.recycle();
            }
        }
    }

    private String simpleClassName(CharSequence className) {
        if (className == null) {
            return "";
        }
        String cls = className.toString();
        int dotIdx = cls.lastIndexOf('.');
        return dotIdx >= 0 ? cls.substring(dotIdx + 1) : cls;
    }

    private String truncate(CharSequence value, int maxLength) {
        if (value == null) {
            return null;
        }
        if (value.length() <= maxLength) {
            return value.toString();
        }
        return value.subSequence(0, maxLength) + "...";
    }

    private void addNullableString(JsonObject object, String key, String value) {
        if (value == null || value.isEmpty()) {
            object.add(key, JsonNull.INSTANCE);
        } else {
            object.addProperty(key, value);
        }
    }

    /**
     * Full node tree builder - outputs ALL nodes with ALL properties, no filtering.
     */
    private void buildNodeTreeFull(AccessibilityNodeInfo node, StringBuilder sb, int depth) {
        if (node == null) {
            return;
        }

        String indent = "  ".repeat(depth);
        sb.append(indent);

        // className
        CharSequence className = node.getClassName();
        if (className != null) {
            String cls = className.toString();
            int dotIdx = cls.lastIndexOf('.');
            sb.append("[").append(dotIdx >= 0 ? cls.substring(dotIdx + 1) : cls).append("]");
        }

        // text
        if (node.getText() != null && node.getText().length() > 0) {
            CharSequence text = node.getText();
            if (text.length() > 200) {
                sb.append(" text=\"").append(text.subSequence(0, 200)).append("...\"");
            } else {
                sb.append(" text=\"").append(text).append("\"");
            }
        }

        // contentDescription
        if (node.getContentDescription() != null && node.getContentDescription().length() > 0) {
            sb.append(" desc=\"").append(node.getContentDescription()).append("\"");
        }

        // resource-id
        String resId = node.getViewIdResourceName();
        if (resId != null && !resId.isEmpty()) {
            sb.append(" id=\"").append(resId).append("\"");
        }

        // package
        if (node.getPackageName() != null) {
            sb.append(" pkg=\"").append(node.getPackageName()).append("\"");
        }

        // interaction states
        if (node.isClickable()) sb.append(" [clickable]");
        if (node.isLongClickable()) sb.append(" [long-clickable]");
        if (node.isScrollable()) sb.append(" [scrollable]");
        if (node.isEditable()) sb.append(" [editable]");
        if (node.isCheckable()) sb.append(node.isChecked() ? " [checked]" : " [unchecked]");
        if (!node.isEnabled()) sb.append(" [disabled]");
        if (node.isFocused()) sb.append(" [focused]");
        if (node.isSelected()) sb.append(" [selected]");
        if (!node.isVisibleToUser()) sb.append(" [invisible]");

        // slider range info
        if (isSliderNode(node)) {
            sb.append(" [slider]");
            AccessibilityNodeInfo.RangeInfo rangeInfo = node.getRangeInfo();
            if (rangeInfo != null) {
                sb.append(String.format(" range=[%.0f-%.0f, current=%.0f]",
                        rangeInfo.getMin(), rangeInfo.getMax(), rangeInfo.getCurrent()));
            }
        }

        // progress bar
        CharSequence cn = node.getClassName();
        if (cn != null && cn.toString().contains("ProgressBar")) {
            sb.append(" [loading]");
        }

        // bounds
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        sb.append(" bounds=").append(bounds.toShortString());

        sb.append("\n");

        // recurse all children
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                buildNodeTreeFull(child, sb, depth + 1);
                child.recycle();
            }
        }
    }

    /**
     * Recycles a list of AccessibilityNodeInfo nodes.
     * Call this after you are done using nodes returned by findNodesByText/findNodesById/findNodesByDescription.
     */
    public static void recycleNodes(List<AccessibilityNodeInfo> nodes) {
        if (nodes == null) return;
        for (AccessibilityNodeInfo node : nodes) {
            if (node != null) {
                try {
                    node.recycle();
                } catch (Exception ignored) {
                    // Already recycled
                }
            }
        }
    }

    /**
     * Finds a specific node and returns detailed info as a string.
     */
    public String getNodeDetail(AccessibilityNodeInfo node) {
        if (node == null) {
            return "null";
        }
        StringBuilder sb = new StringBuilder();
        sb.append("class=").append(node.getClassName());
        if (node.getText() != null) {
            sb.append(", text=\"").append(node.getText()).append("\"");
        }
        if (node.getContentDescription() != null) {
            sb.append(", desc=\"").append(node.getContentDescription()).append("\"");
        }
        sb.append(", clickable=").append(node.isClickable());
        sb.append(", enabled=").append(node.isEnabled());
        sb.append(", visible=").append(node.isVisibleToUser());
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        sb.append(", bounds=").append(bounds.toShortString());
        return sb.toString();
    }

    // ======================== Slider Detection (for buildNodeTree) ========================

    /**
     * Check if a node is a slider/seekbar type.
     * Used by buildNodeTree to ensure slider nodes are included in screen info.
     */
    private boolean isSliderNode(AccessibilityNodeInfo node) {
        CharSequence className = node.getClassName();
        if (className == null) return false;
        String cls = className.toString();
        return cls.contains("SeekBar")
                || cls.contains("Slider")
                || cls.contains("RatingBar")
                || node.getRangeInfo() != null;
    }

    // ======================== Global Actions ========================

    public boolean pressBack() {
        return performGlobalAction(GLOBAL_ACTION_BACK);
    }

    public boolean pressHome() {
        return performGlobalAction(GLOBAL_ACTION_HOME);
    }

    public boolean openRecentApps() {
        return performGlobalAction(GLOBAL_ACTION_RECENTS);
    }

    public boolean expandNotifications() {
        return performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS);
    }

    public boolean collapseNotifications() {
        return performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS);
    }

    public boolean lockScreen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            return performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN);
        }
        return false;
    }

    /**
     * Attempts to unlock the screen: wake up + swipe up.
     * Works for no-password / swipe lock screens.
     * If the device has PIN/pattern/password, the swipe will bring up the input screen.
     */
    public boolean unlockScreen() {
        try {
            // 1. 唤醒屏幕
            android.os.PowerManager pm = (android.os.PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null && !pm.isInteractive()) {
                @SuppressWarnings("deprecation")
                android.os.PowerManager.WakeLock wl = pm.newWakeLock(
                        android.os.PowerManager.SCREEN_DIM_WAKE_LOCK | android.os.PowerManager.ACQUIRE_CAUSES_WAKEUP,
                        "AgentPhone:unlock"
                );
                wl.acquire(3000);
                wl.release();
                // 等屏幕亮起
                try { Thread.sleep(500); } catch (InterruptedException ignored) {}
            }

            // 2. 模拟上滑手势解锁
            android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
            int centerX = dm.widthPixels / 2;
            int bottomY = (int) (dm.heightPixels * 0.8);
            int topY = (int) (dm.heightPixels * 0.2);
            return performSwipe(centerX, bottomY, centerX, topY, 300);
        } catch (Exception e) {
            XLog.e(TAG, "unlockScreen failed", e);
            return false;
        }
    }

    // ======================== Screenshot ========================

    /**
     * Takes a screenshot (requires API 30+).
     * Returns the bitmap or null on failure.
     */
    public Bitmap takeScreenshot(long timeoutMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return null;
        }
        synchronized (screenshotLock) {
            long now = System.currentTimeMillis();
            Bitmap cached = copyCachedScreenshot(now, SCREENSHOT_CACHE_TTL_MS);
            if (cached != null) {
                return cached;
            }

            waitForScreenshotCooldown(now);

            Bitmap bitmap = captureScreenshotOnce(timeoutMs);
            if (bitmap == null) {
                waitForScreenshotCooldown(System.currentTimeMillis());
                bitmap = captureScreenshotOnce(Math.max(timeoutMs, 5000L));
            }

            now = System.currentTimeMillis();
            if (bitmap == null) {
                lastScreenshotAt = now;
                Bitmap stale = copyCachedScreenshot(now, SCREENSHOT_STALE_FALLBACK_MS);
                if (stale != null) {
                    XLog.w(TAG, "Screenshot capture failed; returning recent cached frame");
                }
                return stale;
            }

            Bitmap ownedBitmap = copyBitmap(bitmap);
            if (ownedBitmap != null) {
                bitmap.recycle();
            } else {
                ownedBitmap = bitmap;
            }
            rememberScreenshot(ownedBitmap, now);
            Bitmap resultBitmap = copyBitmap(ownedBitmap);
            return resultBitmap != null ? resultBitmap : ownedBitmap;
        }
    }

    private Bitmap captureScreenshotOnce(long timeoutMs) {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<Bitmap> bitmapRef = new AtomicReference<>(null);

        takeScreenshot(Display.DEFAULT_DISPLAY, getMainExecutor(),
                new TakeScreenshotCallback() {
                    @Override
                    public void onSuccess(ScreenshotResult result) {
                        Bitmap bmp = Bitmap.wrapHardwareBuffer(
                                result.getHardwareBuffer(), result.getColorSpace());
                        Bitmap copied = copyBitmap(bmp);
                        bitmapRef.set(copied != null ? copied : bmp);
                        if (bmp != null && copied != null) {
                            bmp.recycle();
                        }
                        result.getHardwareBuffer().close();
                        latch.countDown();
                    }

                    @Override
                    public void onFailure(int errorCode) {
                        XLog.e(TAG, "Screenshot failed with error code: " + errorCode);
                        latch.countDown();
                    }
                });

        try {
            latch.await(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return bitmapRef.get();
    }

    private void waitForScreenshotCooldown(long now) {
        long elapsed = now - lastScreenshotAt;
        long waitMs = SCREENSHOT_MIN_INTERVAL_MS - elapsed;
        if (waitMs <= 0) {
            return;
        }
        try {
            Thread.sleep(waitMs);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private Bitmap copyCachedScreenshot(long now, long ttlMs) {
        if (lastScreenshotBitmap == null || lastScreenshotBitmap.isRecycled()) {
            return null;
        }
        if (now - lastScreenshotAt > ttlMs) {
            return null;
        }
        return copyBitmap(lastScreenshotBitmap);
    }

    private void rememberScreenshot(Bitmap bitmap, long capturedAt) {
        if (bitmap == null || bitmap.isRecycled()) {
            return;
        }
        Bitmap cachedCopy = copyBitmap(bitmap);
        if (cachedCopy == null) {
            return;
        }
        recycleLastScreenshot();
        lastScreenshotBitmap = cachedCopy;
        lastScreenshotAt = capturedAt;
    }

    private void recycleLastScreenshot() {
        synchronized (screenshotLock) {
            if (lastScreenshotBitmap != null && !lastScreenshotBitmap.isRecycled()) {
                lastScreenshotBitmap.recycle();
            }
            lastScreenshotBitmap = null;
            lastScreenshotAt = 0L;
        }
    }

    private Bitmap copyBitmap(Bitmap bitmap) {
        if (bitmap == null || bitmap.isRecycled()) {
            return null;
        }
        try {
            Bitmap copied = bitmap.copy(Bitmap.Config.ARGB_8888, false);
            return copied;
        } catch (Exception e) {
            XLog.w(TAG, "Failed to copy screenshot bitmap: " + e.getMessage());
            return null;
        }
    }

    // ======================== Key Event Injection (TV Remote) ========================

    /**
     * Sends a key event via shell command. Works reliably on Android TV boxes.
     *
     * @param keyCode Android KeyEvent keycode (e.g. KeyEvent.KEYCODE_DPAD_UP = 19)
     * @return true if the command executed without error
     */
    public boolean sendKeyEvent(int keyCode) {
        try {
            Process process = Runtime.getRuntime().exec(
                    new String[]{"input", "keyevent", String.valueOf(keyCode)});
            int exitCode = process.waitFor();
            return exitCode == 0;
        } catch (Exception e) {
            XLog.e(TAG, "Failed to send key event: " + keyCode, e);
            return false;
        }
    }

    // ======================== App Launch ========================

    /**
     * Opens an app by its package name.
     */
    public boolean openApp(String packageName) {
        try {
            Intent intent = getPackageManager().getLaunchIntentForPackage(packageName);
            if (intent == null) {
                XLog.e(TAG, "Cannot resolve launch intent for " + packageName);
                return false;
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            return true;
        } catch (Exception e) {
            XLog.e(TAG, "Failed to open app: " + packageName, e);
            return false;
        }
    }
}
