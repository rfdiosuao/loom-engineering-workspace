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

import com.apk.claw.android.rpa.AccessibilitySemanticClickPolicy;
import com.apk.claw.android.rpa.GenerationSnapshot;
import com.apk.claw.android.rpa.UiGenerationTracker;
import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
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
    private final Object screenshotCaptureLock = new Object();
    private final Object screenshotCacheLock = new Object();
    private final ExecutorService screenshotCallbackExecutor =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "apkclaw-screenshot-callback");
                thread.setDaemon(true);
                return thread;
            });
    private final AtomicBoolean screenshotDestroyed = new AtomicBoolean(false);
    private final AtomicReference<ScreenshotCaptureState<CapturedBitmap>> activeScreenshotCapture =
            new AtomicReference<>(null);
    private final UiGenerationTracker generationTracker =
            new UiGenerationTracker(UUID.randomUUID().toString());
    private final AtomicLong frameSequence = new AtomicLong(0L);
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
        if (event == null) {
            return;
        }
        String packageName = event.getPackageName() == null
                ? null
                : event.getPackageName().toString();
        boolean packageChanged = packageName != null
                && !packageName.equals(lastForegroundPackageName);
        if (packageName != null) {
            lastForegroundPackageName = packageName;
            lastForegroundPackageAt = System.currentTimeMillis();
        }
        if (packageChanged || invalidatesUiGeneration(event.getEventType())) {
            generationTracker.markUiChanged();
        }
    }

    private boolean invalidatesUiGeneration(int eventType) {
        switch (eventType) {
            case AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED:
            case AccessibilityEvent.TYPE_WINDOWS_CHANGED:
            case AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED:
            case AccessibilityEvent.TYPE_VIEW_SCROLLED:
            case AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED:
            case AccessibilityEvent.TYPE_VIEW_FOCUSED:
            case AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED:
            case AccessibilityEvent.TYPE_VIEW_SELECTED:
                return true;
            default:
                return false;
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        generationTracker.markUiChanged();
    }

    public GenerationSnapshot getGenerationSnapshot() {
        return generationTracker.snapshot();
    }

    public int getCurrentWindowId() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return -1;
        }
        try {
            return root.getWindowId();
        } finally {
            root.recycle();
        }
    }

    @Override
    public void onInterrupt() {
        XLog.w(TAG, "Accessibility service interrupted");
    }

    @Override
    public void onDestroy() {
        screenshotDestroyed.set(true);
        ScreenshotCaptureState<CapturedBitmap> active = activeScreenshotCapture.getAndSet(null);
        if (active != null) {
            active.cancel();
        }
        screenshotCallbackExecutor.shutdownNow();
        instance = null;
        recycleLastScreenshot();
        super.onDestroy();
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
                generationTracker.markActionDispatched();
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

        generationTracker.markActionDispatched();
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
        try {
            List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByText(text);
            return nodes != null ? nodes : new ArrayList<>();
        } finally {
            root.recycle();
        }
    }

    /**
     * Finds all nodes matching the given view ID (e.g. "com.example:id/button").
     */
    public List<AccessibilityNodeInfo> findNodesById(String viewId) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return new ArrayList<>();
        }
        try {
            List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId(viewId);
            return nodes != null ? nodes : new ArrayList<>();
        } finally {
            root.recycle();
        }
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
            generationTracker.markActionDispatched();
            return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        }
        // Try clicking the parent if the node itself is not clickable
        AccessibilityNodeInfo parent = node.getParent();
        while (parent != null) {
            if (parent.isClickable()) {
                generationTracker.markActionDispatched();
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
     * Clicks a node or clickable ancestor without falling back to coordinates.
     */
    public boolean clickNodeSemantically(AccessibilityNodeInfo node) {
        return AccessibilitySemanticClickPolicy.click(
                node, () -> generationTracker.markActionDispatched());
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
        generationTracker.markActionDispatched();
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

        try {
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
        } finally {
            root.recycle();
        }
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
        generationTracker.markActionDispatched();
        return performGlobalAction(GLOBAL_ACTION_BACK);
    }

    public boolean pressHome() {
        generationTracker.markActionDispatched();
        return performGlobalAction(GLOBAL_ACTION_HOME);
    }

    public boolean openRecentApps() {
        generationTracker.markActionDispatched();
        return performGlobalAction(GLOBAL_ACTION_RECENTS);
    }

    public boolean expandNotifications() {
        generationTracker.markActionDispatched();
        return performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS);
    }

    public boolean collapseNotifications() {
        generationTracker.markActionDispatched();
        return performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS);
    }

    public boolean lockScreen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            generationTracker.markActionDispatched();
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
                generationTracker.markActionDispatched();
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
        ScreenshotFrame frame = takeScreenshotFrameInternal(timeoutMs, 0L, true, true);
        if (frame == null) {
            return null;
        }
        try {
            return frame.detachBitmap();
        } finally {
            frame.close();
        }
    }

    public ScreenshotFrame takeScreenshotFrame(
            long timeoutMs,
            long freshAfterMs,
            boolean allowCachedReadOnly
    ) {
        return takeScreenshotFrameInternal(
                timeoutMs, freshAfterMs, allowCachedReadOnly, false);
    }

    private ScreenshotFrame takeScreenshotFrameInternal(
            long timeoutMs,
            long freshAfterMs,
            boolean allowCachedReadOnly,
            boolean allowLegacyRetry
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return null;
        }
        synchronized (screenshotCaptureLock) {
            if (screenshotDestroyed.get()) {
                return null;
            }
            long now = System.currentTimeMillis();
            if (allowCachedReadOnly) {
                CachedBitmap cached = copyCachedScreenshot(now, SCREENSHOT_CACHE_TTL_MS);
                if (cached != null) {
                    try {
                        return ScreenshotFrame.cached(
                                nextFrameId(false), cached.bitmap, cached.capturedAt, now);
                    } finally {
                        cached.bitmap.recycle();
                    }
                }
            }

            waitForScreenshotCooldown(now);
            CapturedBitmap captured = ScreenshotAttemptPolicy.capture(
                    timeoutMs,
                    allowLegacyRetry,
                    this::captureScreenshotOnceWithTimestamp,
                    () -> waitForScreenshotCooldown(System.currentTimeMillis())
            );
            if (captured != null) {
                try {
                    if (screenshotDestroyed.get()) {
                        return null;
                    }
                    if (captured.capturedAt > freshAfterMs) {
                        rememberScreenshot(captured.bitmap, captured.capturedAt);
                        return ScreenshotFrame.fresh(
                                nextFrameId(true),
                                captured.bitmap,
                                captured.capturedAt,
                                System.currentTimeMillis()
                        );
                    }
                } finally {
                    captured.bitmap.recycle();
                }
            }

            if (!allowCachedReadOnly) {
                return null;
            }
            now = System.currentTimeMillis();
            CachedBitmap stale = copyCachedScreenshot(now, SCREENSHOT_STALE_FALLBACK_MS);
            if (stale == null) {
                return null;
            }
            XLog.w(TAG, "Screenshot capture failed; returning recent cached frame");
            try {
                return ScreenshotFrame.stale(
                        nextFrameId(false), stale.bitmap, stale.capturedAt, now);
            } finally {
                stale.bitmap.recycle();
            }
        }
    }

    private CapturedBitmap captureScreenshotOnceWithTimestamp(long timeoutMs) {
        ScreenshotCaptureState<CapturedBitmap> state =
                new ScreenshotCaptureState<>(captured -> recycleBitmap(captured.bitmap));
        if (!activeScreenshotCapture.compareAndSet(null, state)) {
            return null;
        }
        try {
            if (screenshotDestroyed.get()) {
                state.cancel();
                return null;
            }
            takeScreenshot(Display.DEFAULT_DISPLAY, screenshotCallbackExecutor,
                    new TakeScreenshotCallback() {
                        @Override
                        public void onSuccess(ScreenshotResult result) {
                            long capturedAt = System.currentTimeMillis();
                            Bitmap bmp = null;
                            Bitmap copied = null;
                            try {
                                bmp = Bitmap.wrapHardwareBuffer(
                                        result.getHardwareBuffer(), result.getColorSpace());
                                copied = copyBitmap(bmp);
                                if (copied != null) {
                                    CapturedBitmap captured = new CapturedBitmap(copied, capturedAt);
                                    copied = null;
                                    state.publishOrDispose(captured);
                                } else {
                                    state.fail();
                                }
                            } finally {
                                recycleBitmap(bmp);
                                recycleBitmap(copied);
                                result.getHardwareBuffer().close();
                            }
                        }

                        @Override
                        public void onFailure(int errorCode) {
                            XLog.e(TAG, "Screenshot failed with error code: " + errorCode);
                            state.fail();
                        }
                    });
            return state.await(timeoutMs);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            state.cancel();
            return null;
        } catch (RuntimeException e) {
            state.fail();
            XLog.e(TAG, "Screenshot request failed", e);
            return null;
        } finally {
            activeScreenshotCapture.compareAndSet(state, null);
        }
    }

    private String nextFrameId(boolean callbackProduced) {
        String serviceGeneration = generationTracker.snapshot().getServiceGeneration();
        long sequence = frameSequence.incrementAndGet();
        return serviceGeneration + ":" + sequence + ":"
                + (callbackProduced ? "fresh" : "derived");
    }

    private static final class CapturedBitmap {
        private final Bitmap bitmap;
        private final long capturedAt;

        private CapturedBitmap(Bitmap bitmap, long capturedAt) {
            this.bitmap = bitmap;
            this.capturedAt = capturedAt;
        }
    }

    private static final class CachedBitmap {
        private final Bitmap bitmap;
        private final long capturedAt;

        private CachedBitmap(Bitmap bitmap, long capturedAt) {
            this.bitmap = bitmap;
            this.capturedAt = capturedAt;
        }
    }

    interface CaptureDisposer<T> {
        void dispose(T value);
    }

    static final class ScreenshotCaptureState<T> {
        private static final int WAITING = 0;
        private static final int PUBLISHED = 1;
        private static final int TERMINAL = 2;

        private final CaptureDisposer<T> disposer;
        private int state = WAITING;
        private T published;

        ScreenshotCaptureState(CaptureDisposer<T> disposer) {
            this.disposer = disposer;
        }

        boolean publishOrDispose(T value) {
            boolean accepted;
            synchronized (this) {
                accepted = state == WAITING;
                if (accepted) {
                    published = value;
                    state = PUBLISHED;
                    notifyAll();
                }
            }
            if (!accepted) {
                disposer.dispose(value);
            }
            return accepted;
        }

        T await(long timeoutMs) throws InterruptedException {
            long remainingNanos = TimeUnit.MILLISECONDS.toNanos(Math.max(0L, timeoutMs));
            long deadline = System.nanoTime() + remainingNanos;
            synchronized (this) {
                while (state == WAITING && remainingNanos > 0L) {
                    long waitMillis = TimeUnit.NANOSECONDS.toMillis(remainingNanos);
                    int waitNanos = (int) (remainingNanos
                            - TimeUnit.MILLISECONDS.toNanos(waitMillis));
                    wait(waitMillis, waitNanos);
                    remainingNanos = deadline - System.nanoTime();
                }
                if (state == PUBLISHED) {
                    T value = published;
                    published = null;
                    state = TERMINAL;
                    return value;
                }
                state = TERMINAL;
                return null;
            }
        }

        synchronized void fail() {
            if (state == WAITING) {
                state = TERMINAL;
                notifyAll();
            }
        }

        void cancel() {
            T toDispose = null;
            synchronized (this) {
                if (state == PUBLISHED) {
                    toDispose = published;
                    published = null;
                }
                state = TERMINAL;
                notifyAll();
            }
            if (toDispose != null) {
                disposer.dispose(toDispose);
            }
        }
    }

    interface ScreenshotAttempt<T> {
        T capture(long timeoutMs);
    }

    static final class ScreenshotAttemptPolicy {
        private ScreenshotAttemptPolicy() {
        }

        static <T> T capture(
                long timeoutMs,
                boolean allowLegacyRetry,
                ScreenshotAttempt<T> attempt,
                Runnable beforeRetry
        ) {
            T captured = attempt.capture(timeoutMs);
            if (captured == null && allowLegacyRetry) {
                beforeRetry.run();
                captured = attempt.capture(Math.max(timeoutMs, 5000L));
            }
            return captured;
        }
    }

    private void waitForScreenshotCooldown(long now) {
        long elapsed = now - getLastScreenshotAt();
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

    private long getLastScreenshotAt() {
        synchronized (screenshotCacheLock) {
            return lastScreenshotAt;
        }
    }

    private CachedBitmap copyCachedScreenshot(long now, long ttlMs) {
        synchronized (screenshotCacheLock) {
            if (lastScreenshotBitmap == null || lastScreenshotBitmap.isRecycled()) {
                return null;
            }
            if (now - lastScreenshotAt > ttlMs) {
                return null;
            }
            Bitmap copied = copyBitmap(lastScreenshotBitmap);
            return copied == null ? null : new CachedBitmap(copied, lastScreenshotAt);
        }
    }

    private void rememberScreenshot(Bitmap bitmap, long capturedAt) {
        if (bitmap == null || bitmap.isRecycled()) {
            return;
        }
        Bitmap cachedCopy = copyBitmap(bitmap);
        if (cachedCopy == null) {
            return;
        }
        Bitmap previous = null;
        boolean stored = false;
        synchronized (screenshotCacheLock) {
            if (!screenshotDestroyed.get()) {
                previous = lastScreenshotBitmap;
                lastScreenshotBitmap = cachedCopy;
                lastScreenshotAt = capturedAt;
                stored = true;
            }
        }
        if (!stored) {
            recycleBitmap(cachedCopy);
        }
        recycleBitmap(previous);
    }

    private void recycleLastScreenshot() {
        Bitmap previous;
        synchronized (screenshotCacheLock) {
            previous = lastScreenshotBitmap;
            lastScreenshotBitmap = null;
            lastScreenshotAt = 0L;
        }
        recycleBitmap(previous);
    }

    private void recycleBitmap(Bitmap bitmap) {
        if (bitmap != null && !bitmap.isRecycled()) {
            bitmap.recycle();
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
            generationTracker.markActionDispatched();
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
            generationTracker.markActionDispatched();
            startActivity(intent);
            return true;
        } catch (Exception e) {
            XLog.e(TAG, "Failed to open app: " + packageName, e);
            return false;
        }
    }
}
