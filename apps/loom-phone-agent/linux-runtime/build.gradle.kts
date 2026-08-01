plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.luming.linuxruntime"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.luming.linuxruntime"
        minSdk = 24
        // The companion is distributed outside Play and keeps the executable compatibility mode
        // required by PRoot. The main LumiAgent remains targetSdk 36.
        targetSdk = 28
        versionCode = 1
        versionName = "1.0.0-proot-5.1.107.89-alpine-3.22.5"
    }

    androidResources {
        noCompress += listOf("gz", "tgz")
    }

    sourceSets.named("main") {
        // Ship the license texts and the candidate's exact upstream hashes inside the companion APK.
        assets.directories.add("LICENSES")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    testImplementation(libs.junit)
}
