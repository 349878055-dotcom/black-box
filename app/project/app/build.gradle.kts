plugins {
    id("com.android.application")
}

android {
    namespace = "com.xiami.host"
    compileSdk = 35

    // src/core = native logic; src/ui = HTML/assets/icons
    sourceSets {
        getByName("main") {
            java.setSrcDirs(listOf("../../src/core/java"))
            res.setSrcDirs(listOf("../../src/ui/res"))
            assets.setSrcDirs(listOf("../../src/ui/assets"))
            manifest.srcFile("../../src/core/AndroidManifest.xml")
        }
    }

    defaultConfig {
        applicationId = "com.xiami.host"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // SkillExecutor uses HttpURLConnection (JDK built-in, zero third-party deps).
}
