package com.apk.claw.android.tool.impl;

import com.apk.claw.android.ClawApplication;
import com.apk.claw.android.R;
import com.apk.claw.android.service.ClawAccessibilityService;
import com.apk.claw.android.tool.BaseTool;
import com.apk.claw.android.tool.ToolParameter;
import com.apk.claw.android.tool.ToolResult;

import java.util.Collections;
import java.util.List;
import java.util.Map;

public class GetScreenInfoTool extends BaseTool {

    @Override
    public String getName() {
        return "get_screen_info";
    }

    @Override
    public String getDisplayName() {
        return ClawApplication.Companion.getInstance().getString(R.string.tool_name_get_screen_info);
    }

    @Override
    public String getDescriptionEN() {
        return "Get the current screen's UI hierarchy tree, including all visible elements with their properties (text, id, bounds, clickable, etc.). The result's screen.currentApp / screen.currentPackage tell you which app is in the foreground RIGHT NOW — use them to reliably confirm an app you opened is showing (especially feed-style apps with sparse text), instead of guessing from content. If currentPackage matches the target app, the open succeeded — finish.";
    }

    @Override
    public String getDescriptionCN() {
        return "获取当前屏幕的UI层级树，包括所有可见元素的属性（文本、ID、边界、可点击状态等）。返回里的 screen.currentApp / screen.currentPackage 是当前前台 App 的名称和包名——用它来可靠确认你打开的 App 是否在前台（信息流类 App 文本少时尤其有用），不要靠猜内容。若 currentPackage 等于目标 App，即视为打开成功，直接 finish。";
    }

    @Override
    public List<ToolParameter> getParameters() {
        return Collections.emptyList();
    }

    public static final String SYSTEM_DIALOG_BLOCKED = "__SYSTEM_DIALOG_BLOCKED__";

    /**
     * 切换为完整节点树模式（包含所有节点和全部属性，用于调试）。
     * false = 精简模式（默认，省 token）；true = 完整模式。
     */
    public static boolean useFullTree = false;

    @Override
    public ToolResult execute(Map<String, Object> params) {
        ClawAccessibilityService service = ClawAccessibilityService.getInstance();
        if (service == null) {
            return ToolResult.error("Accessibility service is not running");
        }
        String tree = useFullTree ? service.getScreenTreeFull() : service.getScreenTree();
        if (tree == null) {
            return ToolResult.error(SYSTEM_DIALOG_BLOCKED);
        }
        return ToolResult.success(tree);
    }
}
