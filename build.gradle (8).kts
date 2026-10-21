plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.cxsign.hook"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.cxsign.hook"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            // LSPosed 模块必须签名才能装；用 debug 签名最省事
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")

    // Xposed API 只在编译期需要，运行时由 LSPosed 提供
    compileOnly("de.robv.android.xposed:api:82")
}
