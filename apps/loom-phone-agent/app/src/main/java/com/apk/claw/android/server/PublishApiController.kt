package com.apk.claw.android.server

import com.apk.claw.android.utils.XLog
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD

object PublishApiController {

    private const val TAG = "PublishApiController"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    fun handleExecutePacket(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val packet = ToolApiController.parseJsonBody(session) ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST,
            false,
            null,
            "Invalid JSON body"
        )

        val prompt = buildPublishPrompt(packet)
        val agentBody = JsonObject().apply {
            addProperty("prompt", prompt)
            addProperty("use_template", false)
            addProperty("force_agent", true)
            addProperty("learn_template", false)
            addProperty("read_only", false)
            addProperty("tool_policy", "safe_action")
            addProperty("timeout_sec", 600)
            addProperty("max_rounds", 60)
        }

        XLog.i(TAG, "Executing publish packet: ${packet.get("platformLabel")?.asString ?: packet.get("platformId")?.asString ?: "unknown"}")
        return AgentApiController.handleExecuteTask(
            CachedBodySession(session, agentBody.toString().toByteArray(Charsets.UTF_8))
        )
    }

    private fun buildPublishPrompt(packet: JsonObject): String {
        val platformLabel = packet.getString("platformLabel", packet.getString("platformId", "目标平台"))
        val appName = when (packet.getString("platformId", "").lowercase()) {
            "x" -> "X"
            "xiaohongshu" -> "小红书"
            "douyin" -> "抖音"
            "wechat" -> "微信"
            else -> "目标应用"
        }
        val contentType = packet.getString("contentType", "mixed")
        val title = packet.getString("title", "").trim()
        val body = packet.getString("body", "").trim()
        val notes = packet.getString("notes", "").trim()
        val hashtags = packet.getAsJsonArray("hashtags")
            ?.mapNotNull {
                if (it.isJsonPrimitive) {
                    val tag = it.asString.trim().removePrefix("#")
                    if (tag.isNotBlank()) tag else null
                } else {
                    null
                }
            }
            ?.distinct()
            ?.take(12)
            ?: emptyList()
        val mediaLines = buildMediaLines(packet.getAsJsonArray("media"))

        return buildString {
            appendLine("你现在执行的是 OpenClaw 平台发布任务。")
            appendLine("不要重新生成图片或视频，只使用已经准备好的标题、正文和素材。")
            appendLine("目标平台: $platformLabel")
            appendLine("发布入口: $appName")
            appendLine("内容类型: $contentType")
            appendLine("标题: ${if (title.isNotBlank()) title else "无"}")
            appendLine("正文: ${if (body.isNotBlank()) body else "无"}")
            appendLine("话题: ${if (hashtags.isNotEmpty()) hashtags.joinToString(" ") { "#$it" } else "无"}")
            appendLine("补充要求: ${if (notes.isNotBlank()) notes else "无"}")
            appendLine("已准备素材:")
            if (mediaLines.isNotEmpty()) {
                mediaLines.forEach { appendLine(it) }
            } else {
                appendLine("- 无素材，仅文本发布")
            }
            appendLine()
            appendLine("执行要求:")
            appendLine("- 先进入对应平台的发布入口，再确认当前页面标题。")
            appendLine("- 有素材时按顺序添加，封面需要时先确认封面。")
            appendLine("- 发布前检查预览、可见性、定位、草稿状态和平台提示。")
            appendLine("- 只有在内容正确时才提交发布。")
            appendLine("- 完成后返回是否发布成功、草稿状态和失败原因。")
        }
    }

    private fun buildMediaLines(media: JsonArray?): List<String> {
        if (media == null || media.size() == 0) return emptyList()
        return media.mapIndexed { index, element ->
            if (!element.isJsonObject) {
                "- ${index + 1}. 未知素材"
            } else {
                val obj = element.asJsonObject
                val kind = obj.getString("kind", "image")
                val name = obj.getString("name", "unknown")
                val location = obj.getString("uploadedRelativePath", obj.getString("uploadedPath", obj.getString("sourcePath", "未上传")))
                "- ${index + 1}. $kind / $name / $location"
            }
        }
    }

    private fun JsonObject.getString(key: String, fallback: String): String {
        val element = get(key) ?: return fallback
        return if (element.isJsonPrimitive) element.asString else fallback
    }

    private fun jsonResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: String?,
        error: String?
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", success)
            if (data != null) addProperty("data", data)
            if (error != null) addProperty("error", error)
        }
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }
}
