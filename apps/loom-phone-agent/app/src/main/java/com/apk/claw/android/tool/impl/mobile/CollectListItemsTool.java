package com.apk.claw.android.tool.impl.mobile;

import com.apk.claw.android.collector.ListCollectorService;
import com.apk.claw.android.tool.BaseTool;
import com.apk.claw.android.tool.ToolParameter;
import com.apk.claw.android.tool.ToolResult;

import java.util.Arrays;
import java.util.List;
import java.util.Map;

public class CollectListItemsTool extends BaseTool {

    private final ListCollectorService collector = new ListCollectorService();

    @Override
    public String getName() {
        return "collect_list_items";
    }

    @Override
    public String getDisplayName() {
        return "列表采集";
    }

    @Override
    public String getDescriptionEN() {
        return "Collect structured items from the current scrollable list by reading the screen, scrolling, parsing, and deduplicating. "
                + "Use this instead of repeatedly calling get_screen_info and swipe when the user asks to collect jobs, products, comments, or visible list entries.";
    }

    @Override
    public String getDescriptionCN() {
        return "从当前可滚动列表中采集结构化条目，会自动读屏、滑动、解析和去重。用户要求采集/筛选岗位、商品、评论或列表内容时，优先使用它，而不是反复调用 get_screen_info 和 swipe。";
    }

    @Override
    public List<ToolParameter> getParameters() {
        return Arrays.asList(
                new ToolParameter("target", "string", "List type: job for job cards, product for product cards, generic for a general visible list. Default generic.", false),
                new ToolParameter("max_items", "integer", "Maximum items to collect. Default 20, max 100.", false),
                new ToolParameter("max_swipes", "integer", "Maximum scroll gestures after the current screen. Default 8, max 30.", false),
                new ToolParameter("direction", "string", "Scroll direction: down or up. Default down.", false),
                new ToolParameter("wait_ms", "integer", "Milliseconds to wait after each scroll. Default 650.", false),
                new ToolParameter("return_raw", "boolean", "Whether to include raw screen texts used for each item. Default false.", false),
                new ToolParameter("expected_package", "string", "Optional package that must remain in the foreground while collecting.", false),
                new ToolParameter("allow_sensitive", "boolean", "Allow raw text from sensitive apps such as chat, gallery, files, payments, and banks. Default false.", false)
        );
    }

    @Override
    public ToolResult execute(Map<String, Object> params) {
        ListCollectorService.CollectRequest request = new ListCollectorService.CollectRequest();
        request.target = optionalString(params, "target", "generic");
        request.maxItems = optionalInt(params, "max_items", 20);
        request.maxSwipes = optionalInt(params, "max_swipes", 8);
        request.direction = optionalString(params, "direction", "down");
        request.waitMs = optionalLong(params, "wait_ms", 650L);
        request.returnRaw = optionalBoolean(params, "return_raw", false);
        request.expectedPackage = optionalString(params, "expected_package", "");
        request.allowSensitive = optionalBoolean(params, "allow_sensitive", false);

        ListCollectorService.CollectResult result = collector.collect(request);
        if (!result.success && result.data.get("count").getAsInt() <= 0) {
            return ToolResult.error(result.error != null ? result.error : result.reason);
        }
        return ToolResult.success(result.data.toString());
    }
}
