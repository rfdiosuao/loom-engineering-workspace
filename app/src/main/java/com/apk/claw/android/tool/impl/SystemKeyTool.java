package com.apk.claw.android.tool.impl;

import com.apk.claw.android.ClawApplication;
import com.apk.claw.android.R;
import com.apk.claw.android.service.ClawAccessibilityService;
import com.apk.claw.android.tool.BaseTool;
import com.apk.claw.android.tool.ToolParameter;
import com.apk.claw.android.tool.ToolResult;

import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import android.view.KeyEvent;

public class SystemKeyTool extends BaseTool {

    @Override
    public String getName() {
        return "system_key";
    }

    @Override
    public String getDisplayName() {
        return ClawApplication.Companion.getInstance().getString(R.string.tool_name_system_key);
    }

    @Override
    public String getDescriptionEN() {
        return "Press a system key. Supported keys: back, home, recent_apps/recents, enter, power, volume_up, volume_down, notifications, collapse_notifications, lock_screen, unlock_screen.";
    }

    @Override
    public String getDescriptionCN() {
        return "按下系统按键。支持的按键：back、home、recent_apps/recents、enter、power、volume_up、volume_down、notifications、collapse_notifications、lock_screen、unlock_screen。";
    }

    @Override
    public List<ToolParameter> getParameters() {
        return Collections.singletonList(
                new ToolParameter(
                        "key",
                        "string",
                        "The system key to press. Must be one of: back, home, recent_apps/recents, enter, power, volume_up, volume_down, notifications, collapse_notifications, lock_screen, unlock_screen.",
                        true
                )
        );
    }

    @Override
    public ToolResult execute(Map<String, Object> params) {
        ClawAccessibilityService service = ClawAccessibilityService.getInstance();
        if (service == null) {
            return ToolResult.error("Accessibility service is not running");
        }

        String key = normalizeKey(requireString(params, "key"));
        boolean success;
        String successMsg;

        switch (key) {
            case "back":
                success = service.pressBack();
                successMsg = "Pressed Back button";
                break;
            case "home":
                success = service.pressHome();
                successMsg = "Pressed Home button";
                break;
            case "recent_apps":
                success = service.openRecentApps();
                successMsg = "Opened recent apps";
                break;
            case "enter":
                success = service.sendKeyEvent(KeyEvent.KEYCODE_ENTER);
                successMsg = "Pressed Enter";
                break;
            case "power":
                success = service.sendKeyEvent(KeyEvent.KEYCODE_POWER);
                successMsg = "Pressed Power";
                break;
            case "volume_up":
                success = service.sendKeyEvent(KeyEvent.KEYCODE_VOLUME_UP);
                successMsg = "Pressed Volume Up";
                break;
            case "volume_down":
                success = service.sendKeyEvent(KeyEvent.KEYCODE_VOLUME_DOWN);
                successMsg = "Pressed Volume Down";
                break;
            case "notifications":
                success = service.expandNotifications();
                successMsg = "Expanded notifications";
                break;
            case "collapse_notifications":
                success = service.collapseNotifications();
                successMsg = "Collapsed notifications";
                break;
            case "lock_screen":
                success = service.lockScreen();
                successMsg = "Screen locked";
                break;
            case "unlock_screen":
                success = service.unlockScreen();
                successMsg = "Screen unlock requested";
                break;
            default:
                return ToolResult.error("Unknown system key: " + key + ". Must be one of: back, home, recent_apps/recents, enter, power, volume_up, volume_down, notifications, collapse_notifications, lock_screen, unlock_screen.");
        }

        return success ? ToolResult.success(successMsg)
                : ToolResult.error("Failed to execute " + key);
    }

    private String normalizeKey(String key) {
        String normalized = key == null ? "" : key.trim().toLowerCase(Locale.US);
        switch (normalized) {
            case "recent":
            case "recents":
            case "recent-apps":
            case "recent apps":
                return "recent_apps";
            case "volumeup":
            case "volume-up":
            case "volume up":
                return "volume_up";
            case "volumedown":
            case "volume-down":
            case "volume down":
                return "volume_down";
            default:
                return normalized;
        }
    }
}
