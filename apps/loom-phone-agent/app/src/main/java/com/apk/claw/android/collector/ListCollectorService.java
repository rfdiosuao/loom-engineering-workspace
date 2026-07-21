package com.apk.claw.android.collector;

import com.apk.claw.android.service.ClawAccessibilityService;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ListCollectorService {

    private static final String TAG = "ListCollectorService";
    private static final int DEFAULT_MAX_ITEMS = 20;
    private static final int DEFAULT_MAX_SWIPES = 8;
    private static final int MAX_ITEMS_CAP = 100;
    private static final int MAX_SWIPES_CAP = 30;
    private static final long DEFAULT_WAIT_MS = 650L;
    private static final AtomicBoolean COLLECTOR_RUNNING = new AtomicBoolean(false);
    private static final Set<String> SENSITIVE_PACKAGES = new HashSet<>();
    private static final Set<String> SYSTEM_DIALOG_PACKAGES = new HashSet<>();
    private static final Pattern SALARY_PATTERN = Pattern.compile(
            "(?i)(\\d+(?:\\.\\d+)?\\s*-\\s*\\d+(?:\\.\\d+)?\\s*(?:k|K|千|万|元/天|元/时|元/月|元/年)(?:[·x×]\\d+薪)?)"
                    + "|(\\d+(?:\\.\\d+)?\\s*(?:k|K|千|万)\\s*以上)"
                    + "|(面议)"
    );
    private static final Pattern LOCATION_PATTERN = Pattern.compile(
            "^(北京|上海|广州|深圳|杭州|成都|武汉|南京|苏州|西安|重庆|天津|长沙|郑州|青岛|厦门|合肥|佛山|东莞|宁波|无锡|大连|福州|济南|珠海|南昌|昆明|太原|沈阳|长春|哈尔滨|石家庄|贵阳|南宁|兰州|海口|乌鲁木齐|呼和浩特|银川|西宁|拉萨)(\\s+|$|.*(区|县|市|路|街|镇|园|湾|口|站|旺|桥|村|城|中心))"
    );

    private static final Pattern PRODUCT_PRICE_PATTERN = Pattern.compile(
            "(?:[¥￥]\\s*\\d+(?:\\.\\d+)?)|(?:\\d+(?:\\.\\d+)?\\s*元)"
    );
    private static final Set<String> JOB_NOISE_TEXTS = new HashSet<>();

    static {
        String[] values = {
                "首页", "有了", "消息", "我的", "推荐", "附近", "搜索", "筛选", "职位", "公司", "沟通过",
                "已读", "未读", "立即沟通", "继续沟通", "查看全部", "换一批", "广告", "推广",
                "BOSS直聘", "职位推荐", "职位详情", "搜索职位", "搜索公司", "地图", "在线"
        };
        for (String value : values) {
            JOB_NOISE_TEXTS.add(value);
        }

        String[] sensitivePackages = {
                "com.tencent.mm",
                "com.tencent.mobileqq",
                "com.miui.gallery",
                "com.android.fileexplorer",
                "com.google.android.documentsui",
                "com.estrongs.android.pop",
                "cn.wps.moffice_eng",
                "com.eg.android.AlipayGphone",
                "com.unionpay",
                "com.icbc",
                "com.ecitic.bank.mobile",
                "com.chinamworld.bocmbci",
                "cmb.pb"
        };
        for (String value : sensitivePackages) {
            SENSITIVE_PACKAGES.add(value);
        }

        String[] systemPackages = {
                "android",
                "com.android.permissioncontroller",
                "com.google.android.permissioncontroller",
                "com.miui.securitycore",
                "com.miui.securitycenter",
                "com.miui.securitymanager",
                "com.android.packageinstaller",
                "com.google.android.packageinstaller"
        };
        for (String value : systemPackages) {
            SYSTEM_DIALOG_PACKAGES.add(value);
        }
    }

    public CollectResult collect(CollectRequest request) {
        CollectRequest req = request.normalized();
        ClawAccessibilityService service = ClawAccessibilityService.getInstance();
        if (service == null) {
            return CollectResult.error("accessibility_not_running", "Accessibility service is not running");
        }
        if (!COLLECTOR_RUNNING.compareAndSet(false, true)) {
            return CollectResult.error("collector_busy", "Another list collection is already running");
        }

        try {
        long startedAt = System.currentTimeMillis();
        LinkedHashMap<String, JsonObject> collected = new LinkedHashMap<>();
        JsonArray trace = new JsonArray();
        String previousSignature = null;
        int duplicates = 0;
        int screens = 0;
        int swipes = 0;
        String reason = "max_swipes_reached";
        boolean interrupted = false;

        for (int screenIndex = 0; screenIndex <= req.maxSwipes; screenIndex++) {
            JsonObject tree = service.getScreenTreeJson();
            if (tree == null) {
                reason = collected.isEmpty() ? "screen_tree_unavailable" : "screen_tree_unavailable_partial";
                break;
            }

            screens++;
            ScreenSnapshot snapshot = ScreenSnapshot.from(tree, screenIndex);
            SceneIssue issue = preflight(snapshot, req, collected.isEmpty());
            if (issue != null) {
                if (!collected.isEmpty()) {
                    reason = issue.reason + "_partial";
                    break;
                }
                JsonObject data = emptyData(req, startedAt, screens, swipes, duplicates, interrupted, trace, snapshot, issue);
                return CollectResult.failure(data, issue.reason, issue.message);
            }
            String signature = snapshot.signature();
            boolean unchanged = previousSignature != null && previousSignature.equals(signature);
            if (unchanged && screenIndex > 0) {
                reason = collected.isEmpty() ? "screen_not_changed" : "screen_not_changed_partial";
                break;
            }
            previousSignature = signature;

            List<JsonObject> candidates = parseItems(snapshot, req);
            int added = 0;
            for (JsonObject item : candidates) {
                if (!isAcceptedPackage(stringValue(item, "sourcePackage"), req)) {
                    continue;
                }
                String key = dedupeKey(item, req.target);
                if (key.isEmpty()) {
                    continue;
                }
                if (!collected.containsKey(key)) {
                    collected.put(key, item);
                    added++;
                    if (collected.size() >= req.maxItems) {
                        break;
                    }
                } else {
                    duplicates++;
                }
            }

            trace.add(traceEntry(screenIndex, snapshot, candidates.size(), added, collected.size(), swipes));
            if (collected.size() >= req.maxItems) {
                reason = "collected_enough";
                break;
            }
            if (screenIndex >= req.maxSwipes) {
                reason = "max_swipes_reached";
                break;
            }

            boolean swiped = performScroll(service, snapshot, req.direction);
            if (!swiped) {
                reason = collected.isEmpty() ? "swipe_failed" : "swipe_failed_partial";
                break;
            }
            swipes++;

            try {
                Thread.sleep(req.waitMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                reason = collected.isEmpty() ? "interrupted" : "interrupted_partial";
                interrupted = true;
                break;
            }
        }

        JsonObject data = new JsonObject();
        boolean enough = collected.size() >= req.maxItems;
        boolean partial = !enough;
        boolean hasItems = !collected.isEmpty();
        data.addProperty("partial", partial);
        data.addProperty("reason", enough ? "collected_enough" : reason);
        data.addProperty("target", req.target);
        data.addProperty("requestedCount", req.maxItems);
        data.addProperty("count", collected.size());
        JsonArray items = toLimitedArray(collected, req.maxItems);
        boolean redacted = shouldRedact(items, req);
        data.add("items", redacted ? redactItems(items) : items);
        data.add("stats", stats(startedAt, screens, swipes, duplicates, candidatesCap(req), interrupted));
        data.add("trace", trace);
        data.add("privacy", privacySummary(items, req, redacted));
        data.addProperty("collectedAt", isoNow());

        if (!hasItems) {
            return CollectResult.failure(data, reason, "No list items were collected");
        }
        return CollectResult.success(data, partial);
        } finally {
            COLLECTOR_RUNNING.set(false);
        }
    }

    private SceneIssue preflight(ScreenSnapshot snapshot, CollectRequest request, boolean noItemsYet) {
        if (snapshot.nodes.isEmpty()) {
            return new SceneIssue(
                    "no_accessibility_nodes",
                    "Current screen exposes no accessibility nodes; screenshot/OCR vision mode is required",
                    true
            );
        }
        if (!isAcceptedPackage(snapshot.packageName, request)) {
            String reason = SYSTEM_DIALOG_PACKAGES.contains(snapshot.packageName)
                    ? "system_dialog_blocked"
                    : (noItemsYet ? "wrong_foreground_package" : "foreground_package_changed");
            return new SceneIssue(
                    reason,
                    "Foreground package is " + snapshot.packageName + ", expected " + request.expectedPackage,
                    false
            );
        }
        return null;
    }

    private JsonObject emptyData(
            CollectRequest req,
            long startedAt,
            int screens,
            int swipes,
            int duplicates,
            boolean interrupted,
            JsonArray trace,
            ScreenSnapshot snapshot,
            SceneIssue issue
    ) {
        JsonObject data = new JsonObject();
        data.addProperty("partial", true);
        data.addProperty("reason", issue.reason);
        data.addProperty("target", req.target);
        data.addProperty("requestedCount", req.maxItems);
        data.addProperty("count", 0);
        data.add("items", new JsonArray());
        data.add("stats", stats(startedAt, screens, swipes, duplicates, candidatesCap(req), interrupted));
        data.add("trace", trace);
        data.add("scene", sceneSummary(snapshot, req));
        data.add("privacy", privacySummary(new JsonArray(), req, false));
        data.addProperty("needsVision", issue.needsVision);
        data.addProperty("collectedAt", isoNow());
        return data;
    }

    private JsonObject sceneSummary(ScreenSnapshot snapshot, CollectRequest request) {
        JsonObject scene = new JsonObject();
        scene.addProperty("packageName", snapshot.packageName);
        if (request.expectedPackage != null && !request.expectedPackage.isEmpty()) {
            scene.addProperty("expectedPackage", request.expectedPackage);
            scene.addProperty("expectedPackageMatched", request.expectedPackage.equals(snapshot.packageName));
        }
        scene.addProperty("nodeCount", snapshot.nodes.size());
        scene.addProperty("textNodeCount", snapshot.textNodes().size());
        scene.addProperty("lowTextNodes", snapshot.textNodes().size() < 3);
        scene.addProperty("sensitive", isSensitivePackage(snapshot.packageName));
        scene.addProperty("systemDialog", SYSTEM_DIALOG_PACKAGES.contains(snapshot.packageName));
        return scene;
    }

    private boolean isAcceptedPackage(String packageName, CollectRequest request) {
        return request.expectedPackage == null
                || request.expectedPackage.isEmpty()
                || request.expectedPackage.equals(packageName);
    }

    private boolean shouldRedact(JsonArray items, CollectRequest request) {
        if (request.allowSensitive) {
            return false;
        }
        if (isSensitivePackage(request.expectedPackage)) {
            return true;
        }
        for (JsonElement element : items) {
            if (!element.isJsonObject()) {
                continue;
            }
            if (isSensitivePackage(stringValue(element.getAsJsonObject(), "sourcePackage"))) {
                return true;
            }
        }
        return false;
    }

    private JsonObject privacySummary(JsonArray items, CollectRequest request, boolean redacted) {
        JsonObject privacy = new JsonObject();
        boolean sensitive = isSensitivePackage(request.expectedPackage);
        for (JsonElement element : items) {
            if (element.isJsonObject() && isSensitivePackage(stringValue(element.getAsJsonObject(), "sourcePackage"))) {
                sensitive = true;
                break;
            }
        }
        privacy.addProperty("sensitive", sensitive);
        privacy.addProperty("allowSensitive", request.allowSensitive);
        privacy.addProperty("redacted", redacted);
        privacy.addProperty("mode", redacted ? "metadata_only" : "full_text");
        return privacy;
    }

    private JsonArray redactItems(JsonArray items) {
        JsonArray redactedItems = new JsonArray();
        for (JsonElement element : items) {
            if (!element.isJsonObject()) {
                continue;
            }
            JsonObject original = element.getAsJsonObject();
            JsonObject copy = original.deepCopy();
            JsonObject textShape = new JsonObject();
            redactField(copy, textShape, "title");
            redactField(copy, textShape, "subtitle");
            redactField(copy, textShape, "salary");
            redactField(copy, textShape, "company");
            redactField(copy, textShape, "location");
            copy.remove("rawTexts");
            copy.addProperty("redacted", true);
            copy.add("textShape", textShape);
            redactedItems.add(copy);
        }
        return redactedItems;
    }

    private void redactField(JsonObject item, JsonObject textShape, String field) {
        JsonElement element = item.get(field);
        if (element == null || element.isJsonNull()) {
            return;
        }
        String value = stringValue(item, field);
        JsonObject shape = new JsonObject();
        shape.addProperty("length", cleanText(value).length());
        shape.addProperty("hasDigit", value.matches(".*\\d.*"));
        shape.addProperty("hasCjk", value.matches(".*[\\u4E00-\\u9FFF].*"));
        textShape.add(field, shape);
        item.addProperty(field, "[redacted len=" + cleanText(value).length() + "]");
    }

    private boolean isSensitivePackage(String packageName) {
        return packageName != null && SENSITIVE_PACKAGES.contains(packageName);
    }

    private List<JsonObject> parseItems(ScreenSnapshot snapshot, CollectRequest request) {
        if ("job".equals(request.target) || "jobs".equals(request.target) || "position".equals(request.target)) {
            return parseJobItems(snapshot, request);
        }
        if ("product".equals(request.target) || "goods".equals(request.target) || "item".equals(request.target)) {
            return parseProductItems(snapshot, request);
        }
        return parseGenericItems(snapshot, request);
    }

    private List<JsonObject> parseJobItems(ScreenSnapshot snapshot, CollectRequest request) {
        List<JsonObject> items = new ArrayList<>();
        List<ScreenNode> textNodes = snapshot.textNodes();
        for (ScreenNode salaryNode : textNodes) {
            String salary = salaryNode.text;
            if (!isSalary(salary)) {
                continue;
            }

            int rowTolerance = Math.max(54, (int) (snapshot.height * 0.026f));
            int belowWindow = Math.max(320, (int) (snapshot.height * 0.15f));
            int aboveWindow = Math.max(120, (int) (snapshot.height * 0.055f));
            ScreenNode titleNode = findTitleNearSalary(textNodes, salaryNode, rowTolerance, aboveWindow);
            if (titleNode == null) {
                continue;
            }

            List<ScreenNode> cardNodes = nodesNear(textNodes, salaryNode.top - aboveWindow, salaryNode.bottom + belowWindow);
            ScreenNode companyNode = findCompany(cardNodes, titleNode, salaryNode);
            ScreenNode locationNode = findLocation(cardNodes, titleNode, salaryNode, companyNode);

            JsonObject item = new JsonObject();
            item.addProperty("type", "job");
            item.addProperty("title", cleanText(titleNode.text));
            item.addProperty("salary", cleanText(salary));
            addNullable(item, "company", companyNode == null ? null : cleanText(companyNode.text));
            addNullable(item, "location", locationNode == null ? null : cleanText(locationNode.text));
            addNullable(item, "sourcePackage", snapshot.packageName);
            item.addProperty("screenIndex", snapshot.screenIndex);
            item.addProperty("confidence", confidence(titleNode, salaryNode, companyNode, locationNode));
            item.add("bounds", mergedBounds(cardNodes));
            if (request.returnRaw) {
                item.add("rawTexts", rawTexts(cardNodes));
            }
            items.add(item);
        }
        return items;
    }

    private List<JsonObject> parseGenericItems(ScreenSnapshot snapshot, CollectRequest request) {
        List<JsonObject> items = new ArrayList<>();
        List<ScreenNode> nodes = snapshot.textNodes();
        List<List<ScreenNode>> groups = groupByVerticalBands(nodes, Math.max(90, snapshot.height / 24));
        int index = 0;
        for (List<ScreenNode> group : groups) {
            ScreenNode title = firstMeaningful(group);
            if (title == null || isGenericNoise(title.text)) {
                continue;
            }
            JsonObject item = new JsonObject();
            item.addProperty("type", "generic");
            item.addProperty("title", cleanText(title.text));
            ScreenNode subtitle = firstDifferent(group, title);
            addNullable(item, "subtitle", subtitle == null ? null : cleanText(subtitle.text));
            addNullable(item, "sourcePackage", snapshot.packageName);
            item.addProperty("screenIndex", snapshot.screenIndex);
            item.addProperty("indexOnScreen", index++);
            item.addProperty("confidence", 0.45f);
            item.add("bounds", mergedBounds(group));
            if (request.returnRaw) {
                item.add("rawTexts", rawTexts(group));
            }
            items.add(item);
        }
        return items;
    }

    private List<JsonObject> parseProductItems(ScreenSnapshot snapshot, CollectRequest request) {
        List<JsonObject> items = new ArrayList<>();
        List<ScreenNode> textNodes = snapshot.textNodes();
        for (ScreenNode priceNode : textNodes) {
            String price = productPrice(priceNode.text);
            if (price.isEmpty()) {
                continue;
            }

            ScreenNode titleNode = findProductTitle(textNodes, priceNode, snapshot);
            if (titleNode == null) {
                continue;
            }

            int top = Math.max(0, titleNode.top - Math.max(32, snapshot.height / 80));
            int bottom = Math.min(snapshot.height, priceNode.bottom + Math.max(260, snapshot.height / 10));
            List<ScreenNode> cardNodes = productNodesNear(textNodes, top, bottom);
            List<ScreenNode> boundsNodes = cardNodes.isEmpty() ? nodesNear(textNodes, top, bottom) : cardNodes;
            ScreenNode subtitle = firstProductSubtitle(cardNodes, titleNode, priceNode);

            JsonObject item = new JsonObject();
            item.addProperty("type", "product");
            item.addProperty("title", cleanProductText(titleNode.text));
            item.addProperty("price", price);
            addNullable(item, "subtitle", subtitle == null ? null : cleanProductText(subtitle.text));
            addNullable(item, "sourcePackage", snapshot.packageName);
            item.addProperty("screenIndex", snapshot.screenIndex);
            item.addProperty("confidence", productConfidence(titleNode, priceNode, subtitle));
            item.add("bounds", mergedBounds(boundsNodes));
            if (request.returnRaw) {
                item.add("rawTexts", rawTexts(boundsNodes));
            }
            items.add(item);
        }
        return items;
    }

    private ScreenNode findTitleNearSalary(List<ScreenNode> nodes, ScreenNode salaryNode, int rowTolerance, int aboveWindow) {
        ScreenNode best = null;
        int bestScore = Integer.MIN_VALUE;
        for (ScreenNode node : nodes) {
            if (node == salaryNode || isSalary(node.text) || isJobNoise(node.text)) {
                continue;
            }
            if (node.centerX >= salaryNode.centerX) {
                continue;
            }
            int verticalDistance = Math.abs(node.centerY - salaryNode.centerY);
            boolean sameRow = verticalDistance <= rowTolerance;
            boolean slightlyAbove = node.bottom <= salaryNode.bottom && salaryNode.top - node.top <= aboveWindow;
            if (!sameRow && !slightlyAbove) {
                continue;
            }
            int score = 1000 - verticalDistance - Math.abs(node.left - salaryNode.left) / 6;
            if (looksLikeJobTitle(node.text)) {
                score += 180;
            }
            if (node.width > 120) {
                score += 60;
            }
            if (score > bestScore) {
                best = node;
                bestScore = score;
            }
        }
        return best;
    }

    private ScreenNode findCompany(List<ScreenNode> nodes, ScreenNode titleNode, ScreenNode salaryNode) {
        ScreenNode best = null;
        int bestScore = Integer.MIN_VALUE;
        for (ScreenNode node : nodes) {
            if (node == titleNode || node == salaryNode) {
                continue;
            }
            if (!isCompanyCandidate(node.text)) {
                continue;
            }
            if (node.centerY < Math.min(titleNode.centerY, salaryNode.centerY) - 20) {
                continue;
            }
            int dy = Math.max(0, node.top - salaryNode.bottom);
            int score = 600 - dy - Math.abs(node.left - titleNode.left) / 4;
            if (node.left <= titleNode.left + 120) {
                score += 120;
            }
            if (LOCATION_PATTERN.matcher(node.text).find()) {
                score -= 220;
            }
            if (score > bestScore) {
                best = node;
                bestScore = score;
            }
        }
        return best;
    }

    private ScreenNode findLocation(List<ScreenNode> nodes, ScreenNode titleNode, ScreenNode salaryNode, ScreenNode companyNode) {
        ScreenNode best = null;
        int bestScore = Integer.MIN_VALUE;
        for (ScreenNode node : nodes) {
            if (node == titleNode || node == salaryNode || node == companyNode) {
                continue;
            }
            if (!isLocationCandidate(node.text)) {
                continue;
            }
            int dy = Math.abs(node.centerY - (companyNode == null ? salaryNode.centerY : companyNode.centerY));
            int score = 500 - dy;
            if (node.centerX > titleNode.centerX) {
                score += 60;
            }
            if (score > bestScore) {
                best = node;
                bestScore = score;
            }
        }
        return best;
    }

    private List<ScreenNode> nodesNear(List<ScreenNode> nodes, int top, int bottom) {
        List<ScreenNode> result = new ArrayList<>();
        for (ScreenNode node : nodes) {
            if (node.bottom >= top && node.top <= bottom && !isJobNoise(node.text)) {
                result.add(node);
            }
        }
        return result;
    }

    private List<List<ScreenNode>> groupByVerticalBands(List<ScreenNode> nodes, int bandHeight) {
        List<List<ScreenNode>> groups = new ArrayList<>();
        List<ScreenNode> current = new ArrayList<>();
        int currentTop = Integer.MIN_VALUE;
        for (ScreenNode node : nodes) {
            if (isGenericNoise(node.text)) {
                continue;
            }
            if (current.isEmpty() || node.top - currentTop <= bandHeight) {
                current.add(node);
                if (currentTop == Integer.MIN_VALUE) {
                    currentTop = node.top;
                }
            } else {
                groups.add(current);
                current = new ArrayList<>();
                current.add(node);
                currentTop = node.top;
            }
        }
        if (!current.isEmpty()) {
            groups.add(current);
        }
        return groups;
    }

    private ScreenNode firstMeaningful(List<ScreenNode> nodes) {
        for (ScreenNode node : nodes) {
            if (!isGenericNoise(node.text) && node.text.length() >= 2) {
                return node;
            }
        }
        return null;
    }

    private ScreenNode firstDifferent(List<ScreenNode> nodes, ScreenNode title) {
        for (ScreenNode node : nodes) {
            if (node != title && !node.text.equals(title.text) && !isGenericNoise(node.text)) {
                return node;
            }
        }
        return null;
    }

    private ScreenNode findProductTitle(List<ScreenNode> nodes, ScreenNode priceNode, ScreenSnapshot snapshot) {
        ScreenNode best = null;
        int bestScore = Integer.MIN_VALUE;
        int aboveWindow = Math.max(360, snapshot.height / 7);
        for (ScreenNode node : nodes) {
            if (node == priceNode || !isProductTitleCandidate(node.text)) {
                continue;
            }
            if (node.top > priceNode.top + 20 || priceNode.top - node.top > aboveWindow) {
                continue;
            }
            if (node.right < priceNode.left - 60 || node.left > priceNode.right + Math.max(360, snapshot.width / 3)) {
                continue;
            }
            int verticalDistance = Math.abs(priceNode.top - node.top);
            int horizontalDistance = Math.abs(priceNode.left - node.left);
            int score = 1200 - verticalDistance - horizontalDistance / 4 + Math.min(node.width, 900) / 4;
            if (node.text.length() > 16) {
                score += 120;
            }
            if (node.left <= priceNode.left + 40 && node.right >= priceNode.left + 180) {
                score += 80;
            }
            if (score > bestScore) {
                best = node;
                bestScore = score;
            }
        }
        return best;
    }

    private List<ScreenNode> productNodesNear(List<ScreenNode> nodes, int top, int bottom) {
        List<ScreenNode> result = new ArrayList<>();
        for (ScreenNode node : nodes) {
            if (node.bottom >= top && node.top <= bottom && !isProductNoise(node.text)) {
                result.add(node);
            }
        }
        return result;
    }

    private ScreenNode firstProductSubtitle(List<ScreenNode> nodes, ScreenNode title, ScreenNode price) {
        for (ScreenNode node : nodes) {
            if (node == title || node == price || isProductNoise(node.text) || productPrice(node.text).length() > 0) {
                continue;
            }
            if (node.top < title.bottom || node.top > price.top + 260) {
                continue;
            }
            String value = cleanProductText(node.text);
            if (value.length() >= 2 && value.length() <= 80) {
                return node;
            }
        }
        return null;
    }

    private boolean performScroll(ClawAccessibilityService service, ScreenSnapshot snapshot, String direction) {
        int centerX = snapshot.width / 2;
        int startY;
        int endY;
        if ("up".equals(direction)) {
            startY = (int) (snapshot.height * 0.30f);
            endY = (int) (snapshot.height * 0.74f);
        } else {
            startY = (int) (snapshot.height * 0.76f);
            endY = (int) (snapshot.height * 0.28f);
        }
        return service.performSwipe(centerX, startY, centerX, endY, 430);
    }

    private boolean isSalary(String text) {
        return text != null && SALARY_PATTERN.matcher(cleanText(text)).find();
    }

    private String productPrice(String text) {
        String value = cleanProductText(text);
        if (value.length() < 2 || value.length() > 24) {
            return "";
        }
        Matcher matcher = PRODUCT_PRICE_PATTERN.matcher(value);
        if (!matcher.find()) {
            return "";
        }
        String price = matcher.group();
        if (price == null || price.trim().isEmpty() || "¥".equals(price.trim()) || "￥".equals(price.trim())) {
            return "";
        }
        if (price.indexOf('¥') < 0 && price.indexOf('￥') < 0 && !price.contains("元")) {
            return "";
        }
        return price.replace("￥", "¥").replaceAll("\\s+", "");
    }

    private boolean isProductTitleCandidate(String text) {
        String value = cleanProductText(text);
        if (value.length() < 6 || value.length() > 180) {
            return false;
        }
        if (isProductNoise(value) || productPrice(value).length() > 0) {
            return false;
        }
        if (value.matches("^[\\d.,]+$")) {
            return false;
        }
        return value.matches(".*[\\u4E00-\\u9FFF A-Za-z0-9].*");
    }

    private boolean isProductNoise(String text) {
        String value = cleanProductText(text);
        if (value.isEmpty() || value.length() == 1 || isGenericNoise(value)) {
            return true;
        }
        return "返回".equals(value)
                || "删除".equals(value)
                || "拍照购".equals(value)
                || "显示模式, 列表".equals(value)
                || "全部".equals(value)
                || value.contains("已选中")
                || value.contains("未选中")
                || "综合推荐".equals(value)
                || "销量".equals(value)
                || "筛选".equals(value)
                || "筛选商品".equals(value)
                || "品牌".equals(value)
                || "容量".equals(value)
                || "硬盘类型".equals(value)
                || "配送时效".equals(value)
                || "京东物流".equals(value)
                || "加购物车".equals(value)
                || "负反馈".equals(value)
                || "广告".equals(value)
                || "浏览记录".equals(value)
                || "打开我的购物车".equals(value)
                || "到手价".equals(value)
                || value.contains("无门槛")
                || value.contains("立减");
    }

    private boolean looksLikeJobTitle(String text) {
        String value = cleanText(text);
        if (value.length() < 2 || value.length() > 64) {
            return false;
        }
        if (isSalary(value) || isLocationCandidate(value) || isJobNoise(value)) {
            return false;
        }
        return value.contains("AI")
                || value.contains("ai")
                || value.contains("Agent")
                || value.contains("工程师")
                || value.contains("产品")
                || value.contains("实习")
                || value.contains("开发")
                || value.contains("运营")
                || value.contains("算法")
                || value.contains("经理");
    }

    private boolean isCompanyCandidate(String text) {
        String value = cleanText(text);
        if (value.length() < 2 || value.length() > 40) {
            return false;
        }
        if (isSalary(value) || isJobNoise(value) || isJobTag(value)) {
            return false;
        }
        return !value.contains("·") && !LOCATION_PATTERN.matcher(value).find();
    }

    private boolean isLocationCandidate(String text) {
        String value = cleanText(text);
        if (value.length() < 2 || value.length() > 40) {
            return false;
        }
        return LOCATION_PATTERN.matcher(value).find();
    }

    private boolean isJobTag(String text) {
        String value = cleanText(text);
        return value.contains("本科")
                || value.contains("硕士")
                || value.contains("博士")
                || value.contains("经验")
                || value.contains("在校")
                || value.contains("应届")
                || value.contains("不限")
                || value.contains("天/周")
                || value.contains("个月")
                || value.contains("融资")
                || value.contains("人以上");
    }

    private boolean isJobNoise(String text) {
        String value = cleanText(text);
        if (value.isEmpty() || JOB_NOISE_TEXTS.contains(value)) {
            return true;
        }
        return value.length() == 1 && !value.matches("[A-Za-z0-9]");
    }

    private boolean isGenericNoise(String text) {
        String value = cleanText(text);
        return value.isEmpty()
                || value.length() == 1
                || JOB_NOISE_TEXTS.contains(value)
                || "返回".equals(value)
                || "关闭".equals(value)
                || "更多".equals(value);
    }

    private String dedupeKey(JsonObject item, String target) {
        String title = stringValue(item, "title");
        String salary = stringValue(item, "salary");
        String company = stringValue(item, "company");
        String subtitle = stringValue(item, "subtitle");
        String price = stringValue(item, "price");
        String base;
        if ("job".equals(target) || "jobs".equals(target) || "position".equals(target)) {
            base = title + "|" + company + "|" + salary;
        } else if ("product".equals(target) || "goods".equals(target) || "item".equals(target)) {
            base = title + "|" + price;
        } else {
            base = title + "|" + subtitle;
        }
        return normalizeKey(base);
    }

    private String normalizeKey(String value) {
        return cleanText(value).toLowerCase(Locale.US).replaceAll("\\s+", "");
    }

    private String stringValue(JsonObject object, String key) {
        JsonElement element = object.get(key);
        if (element == null || element.isJsonNull()) {
            return "";
        }
        try {
            return element.getAsString();
        } catch (Exception e) {
            return "";
        }
    }

    private float confidence(ScreenNode titleNode, ScreenNode salaryNode, ScreenNode companyNode, ScreenNode locationNode) {
        float score = 0.45f;
        if (titleNode != null) score += 0.18f;
        if (salaryNode != null) score += 0.20f;
        if (companyNode != null) score += 0.10f;
        if (locationNode != null) score += 0.07f;
        return Math.min(0.98f, score);
    }

    private float productConfidence(ScreenNode titleNode, ScreenNode priceNode, ScreenNode subtitleNode) {
        float score = 0.52f;
        if (titleNode != null) score += 0.22f;
        if (priceNode != null) score += 0.18f;
        if (subtitleNode != null) score += 0.06f;
        return Math.min(0.98f, score);
    }

    private JsonObject mergedBounds(List<ScreenNode> nodes) {
        if (nodes == null || nodes.isEmpty()) {
            return new JsonObject();
        }
        int left = Integer.MAX_VALUE;
        int top = Integer.MAX_VALUE;
        int right = Integer.MIN_VALUE;
        int bottom = Integer.MIN_VALUE;
        for (ScreenNode node : nodes) {
            left = Math.min(left, node.left);
            top = Math.min(top, node.top);
            right = Math.max(right, node.right);
            bottom = Math.max(bottom, node.bottom);
        }
        JsonObject bounds = new JsonObject();
        bounds.addProperty("left", left);
        bounds.addProperty("top", top);
        bounds.addProperty("right", right);
        bounds.addProperty("bottom", bottom);
        bounds.addProperty("width", Math.max(0, right - left));
        bounds.addProperty("height", Math.max(0, bottom - top));
        bounds.addProperty("centerX", (left + right) / 2);
        bounds.addProperty("centerY", (top + bottom) / 2);
        return bounds;
    }

    private JsonArray rawTexts(List<ScreenNode> nodes) {
        JsonArray array = new JsonArray();
        for (ScreenNode node : nodes) {
            array.add(node.text);
        }
        return array;
    }

    private JsonArray toLimitedArray(LinkedHashMap<String, JsonObject> collected, int limit) {
        JsonArray array = new JsonArray();
        int count = 0;
        for (JsonObject item : collected.values()) {
            if (count++ >= limit) {
                break;
            }
            array.add(item);
        }
        return array;
    }

    private JsonObject traceEntry(int screenIndex, ScreenSnapshot snapshot, int candidates, int added, int total, int swipes) {
        JsonObject object = new JsonObject();
        object.addProperty("screenIndex", screenIndex);
        object.addProperty("packageName", snapshot.packageName);
        object.addProperty("textNodeCount", snapshot.textNodes().size());
        object.addProperty("candidateCount", candidates);
        object.addProperty("addedCount", added);
        object.addProperty("totalCount", total);
        object.addProperty("swipesBeforeScreen", swipes);
        return object;
    }

    private JsonObject stats(long startedAt, int screens, int swipes, int duplicates, int candidatesCap, boolean interrupted) {
        JsonObject stats = new JsonObject();
        stats.addProperty("screens", screens);
        stats.addProperty("swipes", swipes);
        stats.addProperty("duplicates", duplicates);
        stats.addProperty("maxCandidateItems", candidatesCap);
        stats.addProperty("durationMs", System.currentTimeMillis() - startedAt);
        stats.addProperty("interrupted", interrupted);
        return stats;
    }

    private int candidatesCap(CollectRequest req) {
        return Math.max(req.maxItems, 1);
    }

    private void addNullable(JsonObject object, String key, String value) {
        if (value == null || value.trim().isEmpty()) {
            object.add(key, JsonNull.INSTANCE);
        } else {
            object.addProperty(key, value);
        }
    }

    private String cleanText(String text) {
        if (text == null) {
            return "";
        }
        return text.replace('\u00A0', ' ').trim().replaceAll("\\s+", " ");
    }

    private String cleanProductText(String text) {
        if (text == null) {
            return "";
        }
        return cleanText(text)
                .replaceAll("[\\u200B-\\u200F\\u202A-\\u202E\\u2060\\uFEFF]", "")
                .replaceAll("\\s+", " ")
                .trim();
    }

    private String isoNow() {
        return new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(new Date());
    }

    public static class CollectRequest {
        public String target = "generic";
        public int maxItems = DEFAULT_MAX_ITEMS;
        public int maxSwipes = DEFAULT_MAX_SWIPES;
        public String direction = "down";
        public long waitMs = DEFAULT_WAIT_MS;
        public boolean returnRaw = false;
        public String expectedPackage = "";
        public boolean allowSensitive = false;

        public CollectRequest normalized() {
            CollectRequest req = new CollectRequest();
            req.target = normalizeTarget(target);
            req.maxItems = Math.min(Math.max(maxItems, 1), MAX_ITEMS_CAP);
            req.maxSwipes = Math.min(Math.max(maxSwipes, 0), MAX_SWIPES_CAP);
            req.direction = "up".equalsIgnoreCase(direction) ? "up" : "down";
            req.waitMs = Math.min(Math.max(waitMs, 120L), 3000L);
            req.expectedPackage = expectedPackage == null ? "" : expectedPackage.trim();
            req.allowSensitive = allowSensitive;
            req.returnRaw = returnRaw && (req.allowSensitive || !SENSITIVE_PACKAGES.contains(req.expectedPackage));
            return req;
        }

        private String normalizeTarget(String value) {
            if (value == null || value.trim().isEmpty()) {
                return "generic";
            }
            String lower = value.trim().toLowerCase(Locale.US);
            if ("岗位".equals(value) || "职位".equals(value) || "job".equals(lower) || "jobs".equals(lower)
                    || "position".equals(lower) || "positions".equals(lower)) {
                return "job";
            }
            if ("商品".equals(value) || "产品".equals(value) || "product".equals(lower) || "products".equals(lower)
                    || "goods".equals(lower) || "item".equals(lower) || "items".equals(lower)) {
                return "product";
            }
            return lower;
        }
    }

    private static class SceneIssue {
        final String reason;
        final String message;
        final boolean needsVision;

        SceneIssue(String reason, String message, boolean needsVision) {
            this.reason = reason;
            this.message = message;
            this.needsVision = needsVision;
        }
    }

    public static class CollectResult {
        public final boolean success;
        public final boolean partial;
        public final JsonObject data;
        public final String reason;
        public final String error;

        private CollectResult(boolean success, boolean partial, JsonObject data, String reason, String error) {
            this.success = success;
            this.partial = partial;
            this.data = data;
            this.reason = reason;
            this.error = error;
        }

        public static CollectResult success(JsonObject data, boolean partial) {
            return new CollectResult(true, partial, data, data.get("reason").getAsString(), null);
        }

        public static CollectResult failure(JsonObject data, String reason, String error) {
            return new CollectResult(false, true, data, reason, error);
        }

        public static CollectResult error(String reason, String error) {
            JsonObject data = new JsonObject();
            data.addProperty("partial", false);
            data.addProperty("reason", reason);
            data.addProperty("count", 0);
            data.add("items", new JsonArray());
            return new CollectResult(false, false, data, reason, error);
        }
    }

    private static class ScreenSnapshot {
        final int screenIndex;
        final int width;
        final int height;
        final String orientation;
        final String packageName;
        final List<ScreenNode> nodes;
        private List<ScreenNode> textNodes;

        private ScreenSnapshot(int screenIndex, int width, int height, String orientation, String packageName, List<ScreenNode> nodes) {
            this.screenIndex = screenIndex;
            this.width = width;
            this.height = height;
            this.orientation = orientation;
            this.packageName = packageName;
            this.nodes = nodes;
        }

        static ScreenSnapshot from(JsonObject tree, int screenIndex) {
            JsonObject screen = getObject(tree, "screen");
            int width = getInt(screen, "width", 0);
            int height = getInt(screen, "height", 0);
            String orientation = getString(screen, "orientation", "");
            List<ScreenNode> nodes = new ArrayList<>();
            Map<String, Integer> packageCounts = new HashMap<>();
            JsonArray array = tree.getAsJsonArray("nodes");
            if (array != null) {
                for (JsonElement element : array) {
                    if (!element.isJsonObject()) {
                        continue;
                    }
                    ScreenNode node = ScreenNode.from(element.getAsJsonObject());
                    nodes.add(node);
                    if (node.packageName != null && !node.packageName.isEmpty()) {
                        packageCounts.put(node.packageName, packageCounts.getOrDefault(node.packageName, 0) + 1);
                    }
                }
            }
            String packageName = "";
            int maxCount = 0;
            for (Map.Entry<String, Integer> entry : packageCounts.entrySet()) {
                if (entry.getValue() > maxCount) {
                    packageName = entry.getKey();
                    maxCount = entry.getValue();
                }
            }
            return new ScreenSnapshot(screenIndex, width, height, orientation, packageName, nodes);
        }

        List<ScreenNode> textNodes() {
            if (textNodes != null) {
                return textNodes;
            }
            textNodes = new ArrayList<>();
            for (ScreenNode node : nodes) {
                if (!node.text.isEmpty() && node.visible && node.width > 0 && node.height > 0) {
                    textNodes.add(node);
                }
            }
            textNodes.sort((a, b) -> {
                if (a.top != b.top) {
                    return Integer.compare(a.top, b.top);
                }
                return Integer.compare(a.left, b.left);
            });
            return textNodes;
        }

        String signature() {
            StringBuilder builder = new StringBuilder();
            int count = 0;
            for (ScreenNode node : textNodes()) {
                if (count++ >= 80) {
                    break;
                }
                builder.append(node.text).append('@').append(node.top / 8).append(':').append(node.left / 8).append('|');
            }
            return Integer.toHexString(builder.toString().hashCode());
        }
    }

    private static class ScreenNode {
        final String id;
        final String parentId;
        final String className;
        final String text;
        final String resourceId;
        final String packageName;
        final boolean visible;
        final int left;
        final int top;
        final int right;
        final int bottom;
        final int width;
        final int height;
        final int centerX;
        final int centerY;

        private ScreenNode(
                String id,
                String parentId,
                String className,
                String text,
                String resourceId,
                String packageName,
                boolean visible,
                int left,
                int top,
                int right,
                int bottom,
                int width,
                int height,
                int centerX,
                int centerY
        ) {
            this.id = id;
            this.parentId = parentId;
            this.className = className;
            this.text = text;
            this.resourceId = resourceId;
            this.packageName = packageName;
            this.visible = visible;
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
            this.width = width;
            this.height = height;
            this.centerX = centerX;
            this.centerY = centerY;
        }

        static ScreenNode from(JsonObject object) {
            JsonObject bounds = getObject(object, "bounds");
            String text = firstNonBlank(getString(object, "text", ""), getString(object, "description", ""));
            return new ScreenNode(
                    getString(object, "id", ""),
                    getString(object, "parentId", ""),
                    getString(object, "className", ""),
                    text == null ? "" : text.trim().replaceAll("\\s+", " "),
                    getString(object, "resourceId", ""),
                    getString(object, "packageName", ""),
                    getBoolean(object, "visible", true),
                    getInt(bounds, "left", 0),
                    getInt(bounds, "top", 0),
                    getInt(bounds, "right", 0),
                    getInt(bounds, "bottom", 0),
                    getInt(bounds, "width", 0),
                    getInt(bounds, "height", 0),
                    getInt(bounds, "centerX", 0),
                    getInt(bounds, "centerY", 0)
            );
        }
    }

    private static JsonObject getObject(JsonObject object, String key) {
        JsonElement element = object == null ? null : object.get(key);
        return element != null && element.isJsonObject() ? element.getAsJsonObject() : new JsonObject();
    }

    private static String getString(JsonObject object, String key, String defaultValue) {
        JsonElement element = object == null ? null : object.get(key);
        if (element == null || element.isJsonNull()) {
            return defaultValue;
        }
        try {
            return element.getAsString();
        } catch (Exception e) {
            return defaultValue;
        }
    }

    private static int getInt(JsonObject object, String key, int defaultValue) {
        JsonElement element = object == null ? null : object.get(key);
        if (element == null || element.isJsonNull()) {
            return defaultValue;
        }
        try {
            return element.getAsInt();
        } catch (Exception e) {
            return defaultValue;
        }
    }

    private static boolean getBoolean(JsonObject object, String key, boolean defaultValue) {
        JsonElement element = object == null ? null : object.get(key);
        if (element == null || element.isJsonNull()) {
            return defaultValue;
        }
        try {
            return element.getAsBoolean();
        } catch (Exception e) {
            return defaultValue;
        }
    }

    private static String firstNonBlank(String first, String second) {
        if (first != null && !first.trim().isEmpty()) {
            return first;
        }
        return second;
    }
}
