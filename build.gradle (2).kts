plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.cxsign.sentinel"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.cxsign.sentinel"
        minSdk = 24                 // ML Kit 扫码要 21+，前台服务类型要 24+ 更稳
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
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
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.13.1")

    // 离线二维码识别：通知缩略图、相册新图都靠它
    implementation("com.google.mlkit:barcode-scanning:17.2.0")

    // 现成的扫码界面（Google Play Services），省得自己写 CameraX
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")

    // 常驻自动扫码（AutoScanService）：架着手机一直盯着屏幕看
    implementation("androidx.camera:camera-core:1.3.4")
    implementation("androidx.camera:camera-camera2:1.3.4")
    implementation("androidx.camera:camera-lifecycle:1.3.4")
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")
}
