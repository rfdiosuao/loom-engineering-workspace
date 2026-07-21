import org.jetbrains.kotlin.konan.properties.hasProperty
import org.gradle.api.GradleException
import java.io.BufferedReader
import java.io.InputStreamReader
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Properties
import java.util.concurrent.TimeUnit

plugins {
    alias(libs.plugins.android.application)
}

val android7Compat = providers.gradleProperty("android7Compat").orNull.equals("true", ignoreCase = true)
val releaseSigningProperties = Properties().apply {
    rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}

fun releaseSigningProperty(key: String): String {
    return (providers.gradleProperty(key).orNull ?: releaseSigningProperties.getProperty(key, "")).trim()
}

val releaseKeystoreFile = releaseSigningProperty("KEYSTORE_FILE")
val releaseKeystorePassword = releaseSigningProperty("KEYSTORE_PASSWORD")
val releaseKeyAlias = releaseSigningProperty("KEY_ALIAS")
val releaseKeyPassword = releaseSigningProperty("KEY_PASSWORD")

fun releaseBuildRequested(): Boolean {
    return gradle.startParameter.taskNames.any { taskName ->
        taskName.contains("Release", ignoreCase = true)
    }
}

fun validateReleaseSigning() {
    val missing = mutableListOf<String>()
    if (releaseKeystoreFile.isBlank()) {
        missing += "KEYSTORE_FILE"
    } else if (!file(releaseKeystoreFile).exists()) {
        missing += "KEYSTORE_FILE(file not found)"
    }
    if (releaseKeystorePassword.isBlank()) missing += "KEYSTORE_PASSWORD"
    if (releaseKeyAlias.isBlank()) missing += "KEY_ALIAS"
    if (releaseKeyPassword.isBlank()) missing += "KEY_PASSWORD"
    if (missing.isNotEmpty()) {
        throw GradleException(
            "Release signing is incomplete. Set ${missing.joinToString(", ")} in local.properties or Gradle properties before building assembleRelease."
        )
    }
}

if (releaseBuildRequested()) {
    validateReleaseSigning()
}

android {
    namespace = "com.apk.claw.android"
    compileSdk = 36

    signingConfigs {
        create("release") {
            if (releaseKeystoreFile.isNotEmpty()) {
                storeFile = file(releaseKeystoreFile)
                storePassword = releaseKeystorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    defaultConfig {
        applicationId = "com.apk.claw.android"
        minSdk = if (android7Compat) 24 else 28
        targetSdk = 36
        versionCode = 922
        versionName = if (android7Compat) "6.53-stability-android7" else "6.53-stability"
        buildConfigField("String", "VERSION_INFO", getVersionGit())
        buildConfigField("boolean", "ANDROID7_COMPAT", android7Compat.toString())
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }


    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }

        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }

    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    packaging {
        resources {
            excludes += setOf(
                "META-INF/DEPENDENCIES",
                "META-INF/LICENSE",
                "META-INF/LICENSE.txt",
                "META-INF/NOTICE",
                "META-INF/NOTICE.txt",
            )
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.constraintlayout)
    implementation(libs.gson)


    implementation(libs.oapi.sdk)
    if (android7Compat) {
        compileOnly(libs.dingtalk)
    } else {
        implementation(libs.dingtalk)
    }


    // LangChain4j core types are used for messages and tool schemas; model HTTP is Android-safe OkHttp code.
    implementation(libs.langchain4j.core)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.utilcode)
    implementation(libs.ok2curl)
    implementation(libs.lifecycle.runtime)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.mmkv)
    implementation(libs.adapter)
    implementation(libs.glide)
    implementation(libs.glide.transformations)
    implementation(libs.easyfloat)


    // ZXing 二维码/条形码扫描
    implementation(libs.zxing)

    // NanoHTTPD 嵌入式 HTTP 服务器（局域网配置服务）
    implementation(libs.nanohttpd)


    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}

androidComponents {
    onVariants { variant ->
        variant.outputs.forEach { output ->
            if (output is com.android.build.api.variant.impl.VariantOutputImpl) {
                val versionName = android.defaultConfig.versionName ?: "0.0.0"
                val fileName = "AgentPhone_v${versionName}_${getDateTime()}.apk"
                println("output file name: $fileName")
                output.outputFileName.set(fileName)
            }
        }
    }
}

fun getVersionGit(): String {
    val branch = runGit("rev-parse", "--abbrev-ref", "HEAD") ?: "unknown"
    val sha1 = runGit("rev-parse", "HEAD") ?: "unknown"
    return "\"" + branch + "_" + sha1 + "\""
}

fun runGit(vararg args: String): String? {
    return try {
        val process = ProcessBuilder(listOf("git") + args)
            .redirectErrorStream(true)
            .start()
        val reader = BufferedReader(InputStreamReader(process.inputStream))
        val value = reader.readLine()?.trim()
        reader.close()
        if (process.waitFor(2, TimeUnit.SECONDS) && process.exitValue() == 0) value else null
    } catch (_: Exception) {
        null
    }
}

fun getDateTime(): String {
    val df = SimpleDateFormat("yyyyMMdd_HHmmss");
    return df.format(Date());
}

fun getParameter(key: String, defaultValue: String): String {
    var value = defaultValue
    val hasProperty = project.hasProperty(key)
    if (hasProperty) {
        val property = project.properties[key] as String?
        if (!property.isNullOrEmpty()) {
            value = property
            println("get property[$key]from project:$value")
            return value
        }
    }
    val localPropertiesFile = project.rootProject.file("local.properties")
    val localProperties = Properties()
    if (localPropertiesFile.exists()) {
        localProperties.load(localPropertiesFile.inputStream())
        val hasLocalProperty = localProperties.hasProperty(key)
        if (hasLocalProperty) {
            val property = localProperties[key] as String?
            if (!property.isNullOrEmpty()) {
                value = property
                println("get property[$key]from local:$value")
                return value
            }
        }
    }
    println("get property[$key] from default:$value")
    return value
}
