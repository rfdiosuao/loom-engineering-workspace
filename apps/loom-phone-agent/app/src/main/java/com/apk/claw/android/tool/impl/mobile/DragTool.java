package com.apk.claw.android.tool.impl.mobile;

import com.apk.claw.android.service.ClawAccessibilityService;
import com.apk.claw.android.tool.BaseTool;
import com.apk.claw.android.tool.ToolParameter;
import com.apk.claw.android.tool.ToolResult;

import java.util.Arrays;
import java.util.List;
import java.util.Map;

public class DragTool extends BaseTool {

    @Override
    public String getName() {
        return "drag";
    }

    @Override
    public String getDisplayName() {
        return "拖拽";
    }

    @Override
    public String getDescriptionEN() {
        return "Press and hold at a start point, then drag to an end point. Use this for sliders, maps, drag handles, and long-press move gestures; use swipe for normal scrolling.";
    }

    @Override
    public String getDescriptionCN() {
        return "从起点按住一小段时间后拖到终点。适用于滑块、地图、拖拽排序、长按移动图标等；普通滚屏请继续使用 swipe。";
    }

    @Override
    public List<ToolParameter> getParameters() {
        return Arrays.asList(
                new ToolParameter("start_x", "integer", "Start X coordinate", true),
                new ToolParameter("start_y", "integer", "Start Y coordinate", true),
                new ToolParameter("end_x", "integer", "End X coordinate", true),
                new ToolParameter("end_y", "integer", "End Y coordinate", true),
                new ToolParameter("hold_ms", "integer", "Milliseconds to hold before moving (default 350)", false),
                new ToolParameter("duration_ms", "integer", "Drag movement duration in milliseconds (default 700)", false)
        );
    }

    @Override
    public ToolResult execute(Map<String, Object> params) {
        ClawAccessibilityService service = ClawAccessibilityService.getInstance();
        if (service == null) {
            return ToolResult.error("Accessibility service is not running");
        }

        int startX = requireInt(params, "start_x");
        int startY = requireInt(params, "start_y");
        int endX = requireInt(params, "end_x");
        int endY = requireInt(params, "end_y");
        String boundsError = validateCoordinates(startX, startY);
        if (boundsError != null) return ToolResult.error(boundsError);
        boundsError = validateCoordinates(endX, endY);
        if (boundsError != null) return ToolResult.error(boundsError);

        long holdMs = clamp(optionalLong(params, "hold_ms", 350), 80, 2000);
        long durationMs = clamp(optionalLong(params, "duration_ms", 700), 120, 3000);
        boolean success = service.performDrag(startX, startY, endX, endY, holdMs, durationMs);
        return success
                ? ToolResult.success("Dragged from (" + startX + ", " + startY + ") to (" + endX + ", " + endY + "), hold=" + holdMs + "ms, duration=" + durationMs + "ms")
                : ToolResult.error("Failed to drag");
    }

    private long clamp(long value, long min, long max) {
        return Math.max(min, Math.min(max, value));
    }
}
