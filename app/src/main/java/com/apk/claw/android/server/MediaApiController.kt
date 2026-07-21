package com.apk.claw.android.server

import android.content.ContentValues
import android.content.Context
import android.graphics.BitmapFactory
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import com.apk.claw.android.media.ScreenRecordManager
import com.apk.claw.android.utils.XLog
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object MediaApiController {

    private const val TAG = "MediaApiController"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    private const val DEFAULT_ALBUM = "Lumi"
    private const val MAX_IMAGE_BYTES = 32L * 1024L * 1024L
    private const val MAX_VIDEO_BYTES = 512L * 1024L * 1024L

    private val allowedMimeTypes = setOf(
        "image/png",
        "image/jpeg",
        "image/webp"
    )

    private val allowedVideoMimeTypes = setOf(
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-matroska"
    )

    fun handleStartScreenRecord(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session) ?: JsonObject()
        val options = ScreenRecordManager.Options(
            width = getIntAny(json, "width", "video_width", "videoWidth") ?: 0,
            height = getIntAny(json, "height", "video_height", "videoHeight") ?: 0,
            fps = getIntAny(json, "fps", "frame_rate", "frameRate") ?: 30,
            bitRate = getIntAny(json, "bit_rate", "bitRate", "bitrate") ?: 4_000_000,
            maxSeconds = getIntAny(json, "max_seconds", "maxSeconds", "duration_seconds", "durationSeconds") ?: 180,
            filename = getStringAny(json, "filename", "name")
        )
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, ScreenRecordManager.requestStart(context, options), null)
    }

    fun handleStopScreenRecord(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, ScreenRecordManager.stop(context), null)
    }

    fun handleScreenRecordStatus(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, ScreenRecordManager.status(context), null)
    }

    fun handleListVideos(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError
        val data = JsonObject().apply {
            add("recordings", ScreenRecordManager.listRecordings(context))
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleDownloadVideo(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError
        val id = session.parameters["id"]?.firstOrNull()
            ?: session.parameters["filename"]?.firstOrNull()
            ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing video id")
        val file = ScreenRecordManager.resolveRecording(context, id)
            ?: return jsonResponse(NanoHTTPD.Response.Status.NOT_FOUND, false, null, "Video not found")
        val response = NanoHTTPD.newFixedLengthResponse(
            NanoHTTPD.Response.Status.OK,
            "video/mp4",
            file.inputStream(),
            file.length()
        )
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        response.addHeader("Content-Disposition", "attachment; filename=\"${file.name}\"")
        return response
    }

    fun handleImportImage(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val contentLength = session.headers["content-length"]?.toLongOrNull()
            ?: session.headers["Content-Length"]?.toLongOrNull()
            ?: 0L
        if (contentLength > MAX_IMAGE_BYTES + (512L * 1024L)) {
            return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Image is too large. Max size is ${MAX_IMAGE_BYTES / 1024 / 1024} MB"
            )
        }

        val files = mutableMapOf<String, String>()
        try {
            session.parseBody(files)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to parse multipart body: ${e.message}")
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid multipart body")
        }

        val uploadPath = files["file"]
            ?: files["image"]
            ?: files.values.firstOrNull()
            ?: return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Missing image file. Use multipart field 'file'"
            )

        val tempFile = File(uploadPath)
        try {
            if (!tempFile.exists() || !tempFile.isFile || tempFile.length() <= 0L) {
                return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Uploaded file is empty")
            }
            if (tempFile.length() > MAX_IMAGE_BYTES) {
                return jsonResponse(
                    NanoHTTPD.Response.Status.BAD_REQUEST,
                    false,
                    null,
                    "Image is too large. Max size is ${MAX_IMAGE_BYTES / 1024 / 1024} MB"
                )
            }

            val imageInfo = decodeImageInfo(tempFile)
                ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Unsupported or invalid image")
            if (imageInfo.mimeType !in allowedMimeTypes) {
                return jsonResponse(
                    NanoHTTPD.Response.Status.BAD_REQUEST,
                    false,
                    null,
                    "Unsupported image type: ${imageInfo.mimeType}"
                )
            }

            val album = sanitizeSegment(
                session.parameters["album"]?.firstOrNull(),
                DEFAULT_ALBUM
            )
            val filename = buildTargetFilename(
                requestedName = session.parameters["filename"]?.firstOrNull()
                    ?: session.parameters["name"]?.firstOrNull()
                    ?: session.parameters["file"]?.firstOrNull(),
                extension = extensionForMime(imageInfo.mimeType)
            )

            val saved = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                saveWithMediaStore(context, tempFile, album, filename, imageInfo.mimeType)
            } else {
                saveLegacy(context, tempFile, album, filename, imageInfo.mimeType)
            }

            val data = JsonObject().apply {
                addProperty("album", album)
                addProperty("filename", saved.filename)
                addProperty("mimeType", imageInfo.mimeType)
                addProperty("uri", saved.uri)
                addProperty("relativePath", saved.relativePath)
                addProperty("path", saved.path ?: "")
                addProperty("sizeBytes", saved.sizeBytes)
                addProperty("width", imageInfo.width)
                addProperty("height", imageInfo.height)
            }
            XLog.i(TAG, "Imported image to gallery: ${saved.relativePath}, ${saved.sizeBytes} bytes")
            return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to import image: ${e.message}")
            return jsonResponse(
                NanoHTTPD.Response.Status.INTERNAL_ERROR,
                false,
                null,
                "Failed to import image: ${e.message}"
            )
        } finally {
            try {
                tempFile.delete()
            } catch (_: Exception) {
            }
        }
    }

    fun handleImportImageJson(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        val encoded = getStringAny(json, "dataUrl", "data_url", "base64", "imageBase64")
            ?: return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Missing image data. Use dataUrl or base64"
            )
        val bytes = try {
            decodeImageBytes(encoded)
        } catch (e: Exception) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid image data")
        }
        if (bytes.isEmpty()) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Image is empty")
        }
        if (bytes.size > MAX_IMAGE_BYTES) {
            return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Image is too large. Max size is ${MAX_IMAGE_BYTES / 1024 / 1024} MB"
            )
        }

        val tempFile = File.createTempFile("lumi_import_", ".img", context.cacheDir)
        try {
            tempFile.writeBytes(bytes)
            val imageInfo = decodeImageInfo(tempFile)
                ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Unsupported or invalid image")
            if (imageInfo.mimeType !in allowedMimeTypes) {
                return jsonResponse(
                    NanoHTTPD.Response.Status.BAD_REQUEST,
                    false,
                    null,
                    "Unsupported image type: ${imageInfo.mimeType}"
                )
            }

            val album = sanitizeSegment(getStringAny(json, "album"), DEFAULT_ALBUM)
            val filename = buildTargetFilename(
                requestedName = getStringAny(json, "filename", "name", "fileName"),
                extension = extensionForMime(imageInfo.mimeType)
            )
            val saved = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                saveWithMediaStore(context, tempFile, album, filename, imageInfo.mimeType)
            } else {
                saveLegacy(context, tempFile, album, filename, imageInfo.mimeType)
            }
            val data = JsonObject().apply {
                addProperty("album", album)
                addProperty("filename", saved.filename)
                addProperty("mimeType", imageInfo.mimeType)
                addProperty("uri", saved.uri)
                addProperty("relativePath", saved.relativePath)
                addProperty("path", saved.path ?: "")
                addProperty("sizeBytes", saved.sizeBytes)
                addProperty("width", imageInfo.width)
                addProperty("height", imageInfo.height)
            }
            XLog.i(TAG, "Imported signed JSON image to gallery: ${saved.relativePath}, ${saved.sizeBytes} bytes")
            return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to import JSON image: ${e.message}")
            return jsonResponse(
                NanoHTTPD.Response.Status.INTERNAL_ERROR,
                false,
                null,
                "Failed to import image: ${e.message}"
            )
        } finally {
            try {
                tempFile.delete()
            } catch (_: Exception) {
            }
        }
    }

    fun handleImportVideoJson(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val contentLength = session.headers["content-length"]?.toLongOrNull()
            ?: session.headers["Content-Length"]?.toLongOrNull()
            ?: 0L
        val maxJsonVideoBytes = (MAX_VIDEO_BYTES * 4L / 3L) + (8L * 1024L * 1024L)
        if (contentLength > maxJsonVideoBytes) {
            return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Video is too large. Max size is ${MAX_VIDEO_BYTES / 1024 / 1024} MB"
            )
        }

        val json = ToolApiController.parseJsonBody(session)
            ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        val encoded = getStringAny(json, "dataUrl", "data_url", "base64", "videoBase64", "mediaBase64")
            ?: return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Missing video data. Use dataUrl or base64"
            )
        val mimeType = (
            mimeFromDataUrl(encoded)
                ?: getStringAny(json, "mime", "mimeType", "contentType")
                ?: "video/mp4"
            ).lowercase(Locale.US)

        if (mimeType !in allowedVideoMimeTypes) {
            return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Unsupported video type: $mimeType"
            )
        }

        val bytes = try {
            decodeMediaBytes(encoded)
        } catch (e: Exception) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid video data")
        }
        if (bytes.isEmpty()) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Video is empty")
        }
        if (bytes.size > MAX_VIDEO_BYTES) {
            return jsonResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Video is too large. Max size is ${MAX_VIDEO_BYTES / 1024 / 1024} MB"
            )
        }

        val extension = extensionForVideoMime(mimeType)
        val tempFile = File.createTempFile("lumi_video_import_", ".$extension", context.cacheDir)
        try {
            tempFile.writeBytes(bytes)
            val album = sanitizeSegment(getStringAny(json, "album"), DEFAULT_ALBUM)
            val filename = buildTargetFilename(
                requestedName = getStringAny(json, "filename", "name", "fileName"),
                extension = extension,
                prefix = "lumi_video"
            )
            val saved = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                saveVideoWithMediaStore(context, tempFile, album, filename, mimeType)
            } else {
                saveVideoLegacy(context, tempFile, album, filename, mimeType)
            }
            val data = JsonObject().apply {
                addProperty("album", album)
                addProperty("filename", saved.filename)
                addProperty("mimeType", mimeType)
                addProperty("uri", saved.uri)
                addProperty("relativePath", saved.relativePath)
                addProperty("path", saved.path ?: "")
                addProperty("sizeBytes", saved.sizeBytes)
            }
            XLog.i(TAG, "Imported signed JSON video to gallery: ${saved.relativePath}, ${saved.sizeBytes} bytes")
            return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to import JSON video: ${e.message}")
            return jsonResponse(
                NanoHTTPD.Response.Status.INTERNAL_ERROR,
                false,
                null,
                "Failed to import video: ${e.message}"
            )
        } finally {
            try {
                tempFile.delete()
            } catch (_: Exception) {
            }
        }
    }

    private fun saveWithMediaStore(
        context: Context,
        source: File,
        album: String,
        filename: String,
        mimeType: String
    ): SavedImage {
        val relativeDir = "${Environment.DIRECTORY_PICTURES}/$album"
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, filename)
            put(MediaStore.Images.Media.MIME_TYPE, mimeType)
            put(MediaStore.Images.Media.RELATIVE_PATH, relativeDir)
            put(MediaStore.Images.Media.IS_PENDING, 1)
            put(MediaStore.Images.Media.DATE_ADDED, System.currentTimeMillis() / 1000L)
            put(MediaStore.Images.Media.DATE_MODIFIED, System.currentTimeMillis() / 1000L)
        }
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("MediaStore insert returned null")

        try {
            resolver.openOutputStream(uri)?.use { output ->
                source.inputStream().use { input ->
                    input.copyTo(output)
                }
            } ?: throw IllegalStateException("Cannot open MediaStore output stream")

            val doneValues = ContentValues().apply {
                put(MediaStore.Images.Media.IS_PENDING, 0)
            }
            resolver.update(uri, doneValues, null, null)

            return SavedImage(
                uri = uri.toString(),
                relativePath = "$relativeDir/$filename",
                path = null,
                filename = filename,
                sizeBytes = source.length()
            )
        } catch (e: Exception) {
            resolver.delete(uri, null, null)
            throw e
        }
    }

    private fun saveLegacy(
        context: Context,
        source: File,
        album: String,
        filename: String,
        mimeType: String
    ): SavedImage {
        val picturesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)
        val albumDir = File(picturesDir, album)
        if (!albumDir.exists() && !albumDir.mkdirs()) {
            throw IllegalStateException("Cannot create album directory: ${albumDir.absolutePath}")
        }
        val target = dedupeFile(albumDir, filename)
        source.copyTo(target, overwrite = false)
        MediaScannerConnection.scanFile(
            context,
            arrayOf(target.absolutePath),
            arrayOf(mimeType),
            null
        )

        return SavedImage(
            uri = Uri.fromFile(target).toString(),
            relativePath = "${Environment.DIRECTORY_PICTURES}/$album/${target.name}",
            path = target.absolutePath,
            filename = target.name,
            sizeBytes = target.length()
        )
    }

    private fun saveVideoWithMediaStore(
        context: Context,
        source: File,
        album: String,
        filename: String,
        mimeType: String
    ): SavedImage {
        val relativeDir = "${Environment.DIRECTORY_MOVIES}/$album"
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, filename)
            put(MediaStore.Video.Media.MIME_TYPE, mimeType)
            put(MediaStore.Video.Media.RELATIVE_PATH, relativeDir)
            put(MediaStore.Video.Media.IS_PENDING, 1)
            put(MediaStore.Video.Media.DATE_ADDED, System.currentTimeMillis() / 1000L)
            put(MediaStore.Video.Media.DATE_MODIFIED, System.currentTimeMillis() / 1000L)
        }
        val uri = resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("MediaStore insert returned null")

        try {
            resolver.openOutputStream(uri)?.use { output ->
                source.inputStream().use { input ->
                    input.copyTo(output)
                }
            } ?: throw IllegalStateException("Cannot open MediaStore output stream")

            val doneValues = ContentValues().apply {
                put(MediaStore.Video.Media.IS_PENDING, 0)
            }
            resolver.update(uri, doneValues, null, null)

            return SavedImage(
                uri = uri.toString(),
                relativePath = "$relativeDir/$filename",
                path = null,
                filename = filename,
                sizeBytes = source.length()
            )
        } catch (e: Exception) {
            resolver.delete(uri, null, null)
            throw e
        }
    }

    private fun saveVideoLegacy(
        context: Context,
        source: File,
        album: String,
        filename: String,
        mimeType: String
    ): SavedImage {
        val moviesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES)
        val albumDir = File(moviesDir, album)
        if (!albumDir.exists() && !albumDir.mkdirs()) {
            throw IllegalStateException("Cannot create video directory: ${albumDir.absolutePath}")
        }
        val target = dedupeFile(albumDir, filename)
        source.copyTo(target, overwrite = false)
        MediaScannerConnection.scanFile(
            context,
            arrayOf(target.absolutePath),
            arrayOf(mimeType),
            null
        )

        return SavedImage(
            uri = Uri.fromFile(target).toString(),
            relativePath = "${Environment.DIRECTORY_MOVIES}/$album/${target.name}",
            path = target.absolutePath,
            filename = target.name,
            sizeBytes = target.length()
        )
    }

    private fun decodeImageInfo(file: File): ImageInfo? {
        val options = BitmapFactory.Options().apply {
            inJustDecodeBounds = true
        }
        BitmapFactory.decodeFile(file.absolutePath, options)
        val width = options.outWidth
        val height = options.outHeight
        val mimeType = options.outMimeType?.lowercase(Locale.US).orEmpty()
        if (width <= 0 || height <= 0 || mimeType.isBlank()) return null
        return ImageInfo(mimeType = mimeType, width = width, height = height)
    }

    private fun buildTargetFilename(requestedName: String?, extension: String, prefix: String = "lumi_image"): String {
        val fallback = "${prefix}_${timestamp()}.$extension"
        val raw = requestedName
            ?.substringAfterLast('/')
            ?.substringAfterLast('\\')
            ?.takeIf { it.isNotBlank() }
            ?: fallback
        val clean = sanitizeSegment(raw, fallback)
        val base = clean.substringBeforeLast('.', clean).ifBlank { "${prefix}_${timestamp()}" }
        return "$base.$extension"
    }

    private fun sanitizeSegment(value: String?, fallback: String): String {
        val cleaned = value
            ?.trim()
            ?.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_")
            ?.replace(Regex("_+"), "_")
            ?.trim('_', '.', ' ')
            ?.take(80)
            .orEmpty()
        return cleaned.ifBlank { fallback }
    }

    private fun dedupeFile(dir: File, filename: String): File {
        val base = filename.substringBeforeLast('.', filename)
        val extension = filename.substringAfterLast('.', "")
        var candidate = File(dir, filename)
        var index = 1
        while (candidate.exists()) {
            val name = if (extension.isBlank()) {
                "${base}_$index"
            } else {
                "${base}_$index.$extension"
            }
            candidate = File(dir, name)
            index += 1
        }
        return candidate
    }

    private fun extensionForMime(mimeType: String): String {
        return when (mimeType.lowercase(Locale.US)) {
            "image/jpeg" -> "jpg"
            "image/webp" -> "webp"
            else -> "png"
        }
    }

    private fun extensionForVideoMime(mimeType: String): String {
        return when (mimeType.lowercase(Locale.US)) {
            "video/webm" -> "webm"
            "video/quicktime" -> "mov"
            "video/x-matroska" -> "mkv"
            else -> "mp4"
        }
    }

    private fun timestamp(): String {
        return SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
    }

    private fun getIntAny(json: JsonObject, vararg names: String): Int? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asInt
            } catch (_: Exception) {
                null
            }
        }
        return null
    }

    private fun decodeImageBytes(value: String): ByteArray {
        return decodeMediaBytes(value)
    }

    private fun decodeMediaBytes(value: String): ByteArray {
        val trimmed = value.trim()
        val payload = if (trimmed.startsWith("data:", ignoreCase = true)) {
            trimmed.substringAfter(",", "")
        } else {
            trimmed
        }
        return Base64.decode(payload, Base64.DEFAULT)
    }

    private fun mimeFromDataUrl(value: String): String? {
        val trimmed = value.trim()
        if (!trimmed.startsWith("data:", ignoreCase = true)) return null
        val header = trimmed.substringAfter("data:", "").substringBefore(",", "")
        val mime = header.substringBefore(";", "").trim().lowercase(Locale.US)
        return mime.ifBlank { null }
    }

    private fun getStringAny(json: JsonObject, vararg names: String): String? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asString
            } catch (_: Exception) {
                null
            }
        }
        return null
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
        return baseResponse(status, json)
    }

    private fun jsonElementResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonElement?,
        error: String?
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", success)
            if (data != null) add("data", data)
            if (error != null) addProperty("error", error)
        }
        return baseResponse(status, json)
    }

    private fun baseResponse(status: NanoHTTPD.Response.IStatus, json: JsonObject): NanoHTTPD.Response {
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }

    private data class ImageInfo(
        val mimeType: String,
        val width: Int,
        val height: Int
    )

    private data class SavedImage(
        val uri: String,
        val relativePath: String,
        val path: String?,
        val filename: String,
        val sizeBytes: Long
    )
}
