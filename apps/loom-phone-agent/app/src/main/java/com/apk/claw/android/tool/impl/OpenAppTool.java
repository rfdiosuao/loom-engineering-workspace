package com.apk.claw.android.tool.impl;

import android.view.accessibility.AccessibilityNodeInfo;

import com.apk.claw.android.ClawApplication;
import com.apk.claw.android.R;
import com.apk.claw.android.proactive.BehaviorRecorder;
import com.apk.claw.android.service.ClawAccessibilityService;
import com.apk.claw.android.tool.BaseTool;
import com.apk.claw.android.tool.ToolParameter;
import com.apk.claw.android.tool.ToolResult;
import com.apk.claw.android.utils.XLog;

import java.util.Arrays;
import java.util.List;
import java.util.Map;

public class OpenAppTool extends BaseTool {

    private static final String TAG = "OpenAppTool";
    private static final int FOREGROUND_VERIFY_ATTEMPTS = 12;
    private static final long FOREGROUND_VERIFY_INTERVAL_MS = 350L;

    private static final List<String> ALLOW_KEYWORDS = Arrays.asList(
            "本次允许", "仅本次允许", "仅此次允许", "允许一次", "允许本次", "本次打开",
            "允许", "允许打开", "打开",
            "Just once", "Only this time", "Allow", "ALLOW"
    );

    @Override
    public String getName() {
        return "open_app";
    }

    @Override
    public String getDisplayName() {
        return ClawApplication.Companion.getInstance().getString(R.string.tool_name_open_app);
    }

    @Override
    public String getDescriptionEN() {
        return "Open an application by package name and verify that it reached the foreground.";
    }

    @Override
    public String getDescriptionCN() {
        return "通过包名打开应用，并校验目标应用是否真的到达前台。";
    }

    @Override
    public List<ToolParameter> getParameters() {
        return Arrays.asList(
                new ToolParameter("package_name", "string", "The package name of the app to open", true),
                new ToolParameter("verify_foreground", "boolean", "Verify the foreground package after launch. Default true.", false),
                new ToolParameter("check_launch_dialog", "boolean", "Try to dismiss one-time Android launch dialogs. Default true.", false),
                new ToolParameter("force_reopen", "boolean", "Open the app even when it is already foreground. Default false.", false)
        );
    }

    @Override
    public ToolResult execute(Map<String, Object> params) {
        ClawAccessibilityService service = ClawAccessibilityService.getInstance();
        if (service == null) {
            return ToolResult.error("Accessibility service is not running");
        }

        String packageName = requireString(params, "package_name");
        boolean verifyForeground = optionalBoolean(params, "verify_foreground", true);
        boolean checkLaunchDialog = optionalBoolean(params, "check_launch_dialog", true);
        boolean forceReopen = optionalBoolean(params, "force_reopen", false);
        String currentPackage = service.getCurrentPackageName();
        if (!forceReopen && packageName.equals(currentPackage)) {
            BehaviorRecorder.INSTANCE.recordAppOpened(packageName);
            return ToolResult.success("Opened app: " + packageName + ", foreground=" + currentPackage + ", alreadyForeground=true");
        }

        boolean success = service.openApp(packageName);
        if (!success) {
            return ToolResult.error("Failed to open app: " + packageName + ". Make sure the app is installed.");
        }

        if (checkLaunchDialog) {
            dismissChainLaunchDialog(service);
        }

        String foregroundPackage = waitForForegroundPackage(service, packageName, verifyForeground);
        if (verifyForeground && !packageName.equals(foregroundPackage)) {
            String observed = foregroundPackage == null || foregroundPackage.isEmpty() ? "unknown" : foregroundPackage;
            return ToolResult.error(
                    "open_app foreground verification failed: expected=" + packageName
                            + ", actual=" + observed
                            + ". A chooser, system dialog, or previous app may still be in front."
            );
        }

        BehaviorRecorder.INSTANCE.recordAppOpened(packageName);
        return ToolResult.success(
                "Opened app: " + packageName
                        + (foregroundPackage == null ? "" : ", foreground=" + foregroundPackage)
        );
    }

    private String waitForForegroundPackage(ClawAccessibilityService service, String expectedPackage, boolean verify) {
        String observed = service.getCurrentPackageName();
        if (expectedPackage.equals(observed)) {
            return observed;
        }
        int attempts = verify ? FOREGROUND_VERIFY_ATTEMPTS : 2;
        for (int i = 0; i < attempts; i++) {
            sleep(FOREGROUND_VERIFY_INTERVAL_MS);
            observed = service.getCurrentPackageName();
            if (expectedPackage.equals(observed)) {
                return observed;
            }
        }
        return observed;
    }

    private void dismissChainLaunchDialog(ClawAccessibilityService service) {
        for (int attempt = 0; attempt < 3; attempt++) {
            sleep(500);
            for (String keyword : ALLOW_KEYWORDS) {
                List<AccessibilityNodeInfo> nodes = service.findNodesByText(keyword);
                try {
                    for (AccessibilityNodeInfo node : nodes) {
                        CharSequence text = node.getText();
                        if (text != null && matchesAllowButton(text.toString())) {
                            boolean clicked = service.clickNode(node);
                            XLog.i(TAG, "Launch dialog: clicked \"" + text + "\" " + (clicked ? "success" : "failed"));
                            if (clicked) {
                                ClawAccessibilityService.recycleNodes(nodes);
                                return;
                            }
                        }
                    }
                } finally {
                    ClawAccessibilityService.recycleNodes(nodes);
                }
            }
        }
    }

    private boolean matchesAllowButton(String text) {
        String trimmed = text.trim();
        for (String keyword : ALLOW_KEYWORDS) {
            if (trimmed.equals(keyword)) {
                return true;
            }
        }
        return false;
    }

    private void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
