package com.apk.claw.android.server;

import com.apk.claw.android.collector.ListCollectorService;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import fi.iki.elonen.NanoHTTPD;

public final class CollectApiController {

    private static final String MIME_JSON_UTF8 = "application/json; charset=utf-8";
    private static final ListCollectorService COLLECTOR = new ListCollectorService();

    private CollectApiController() {
    }

    public static NanoHTTPD.Response handleCollectList(NanoHTTPD.IHTTPSession session) {
        NanoHTTPD.Response authError = ToolApiController.INSTANCE.checkAuth(session);
        if (authError != null) {
            return authError;
        }

        JsonObject json = ToolApiController.INSTANCE.parseJsonBody(session);
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body");
        }

        ListCollectorService.CollectRequest request = requestFromJson(json);
        ListCollectorService.CollectResult result = COLLECTOR.collect(request);
        return jsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                result.success,
                result.data,
                result.error
        );
    }

    private static ListCollectorService.CollectRequest requestFromJson(JsonObject json) {
        ListCollectorService.CollectRequest request = new ListCollectorService.CollectRequest();
        request.target = getStringAny(json, "target", "type", "scene", "kind");
        if (request.target == null || request.target.trim().isEmpty()) {
            request.target = "generic";
        }
        Integer maxItems = getIntAny(json, "max_items", "maxItems", "count", "limit");
        if (maxItems != null) {
            request.maxItems = maxItems;
        }
        Integer maxSwipes = getIntAny(json, "max_swipes", "maxSwipes", "max_scrolls", "maxScrolls");
        if (maxSwipes != null) {
            request.maxSwipes = maxSwipes;
        }
        String direction = getStringAny(json, "direction", "scroll_direction", "scrollDirection");
        if (direction != null && !direction.trim().isEmpty()) {
            request.direction = direction;
        }
        Integer waitMs = getIntAny(json, "wait_ms", "waitMs", "settle_ms", "settleMs");
        if (waitMs != null) {
            request.waitMs = waitMs;
        }
        Boolean returnRaw = getBooleanAny(json, "return_raw", "returnRaw", "include_raw", "includeRaw");
        if (returnRaw != null) {
            request.returnRaw = returnRaw;
        }
        String expectedPackage = getStringAny(json, "expected_package", "expectedPackage", "package_name", "packageName");
        if (expectedPackage != null && !expectedPackage.trim().isEmpty()) {
            request.expectedPackage = expectedPackage;
        }
        Boolean allowSensitive = getBooleanAny(json, "allow_sensitive", "allowSensitive");
        if (allowSensitive != null) {
            request.allowSensitive = allowSensitive;
        }
        return request;
    }

    private static NanoHTTPD.Response jsonResponse(
            NanoHTTPD.Response.IStatus status,
            boolean success,
            String data,
            String error
    ) {
        JsonObject json = new JsonObject();
        json.addProperty("success", success);
        if (data != null) {
            json.addProperty("data", data);
        }
        if (error != null) {
            json.addProperty("error", error);
        }
        return baseResponse(status, json);
    }

    private static NanoHTTPD.Response jsonElementResponse(
            NanoHTTPD.Response.IStatus status,
            boolean success,
            JsonElement data,
            String error
    ) {
        JsonObject json = new JsonObject();
        json.addProperty("success", success);
        if (data != null) {
            json.add("data", data);
        }
        if (error != null) {
            json.addProperty("error", error);
        }
        return baseResponse(status, json);
    }

    private static NanoHTTPD.Response baseResponse(NanoHTTPD.Response.IStatus status, JsonObject json) {
        NanoHTTPD.Response response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString());
        response.addHeader("Access-Control-Allow-Origin", "*");
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN");
        return response;
    }

    private static String getStringAny(JsonObject json, String... names) {
        for (String name : names) {
            JsonElement value = json.get(name);
            if (value == null || !value.isJsonPrimitive()) {
                continue;
            }
            try {
                return value.getAsString();
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    private static Integer getIntAny(JsonObject json, String... names) {
        for (String name : names) {
            JsonElement value = json.get(name);
            if (value == null || !value.isJsonPrimitive()) {
                continue;
            }
            try {
                return value.getAsInt();
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    private static Boolean getBooleanAny(JsonObject json, String... names) {
        for (String name : names) {
            JsonElement value = json.get(name);
            if (value == null || !value.isJsonPrimitive()) {
                continue;
            }
            try {
                return value.getAsBoolean();
            } catch (Exception ignored) {
            }
        }
        return null;
    }
}
