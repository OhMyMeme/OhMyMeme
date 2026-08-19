import java.util.Properties

val appVersionName = "0.4.6"

val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

fun signProp(name: String): String? = System.getenv(name) ?: keystoreProps.getProperty(name)

plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.ohmymeme.app"
    compileSdk {
        version = release(36)
    }

    signingConfigs {
        create("shared") {
            storeFile = signProp("KEYSTORE_PATH")?.let { rootProject.file(it) }
            storePassword = signProp("KEYSTORE_STORE_PASSWORD")
            keyAlias = signProp("KEYSTORE_KEY_ALIAS")
            keyPassword = signProp("KEYSTORE_KEY_PASSWORD")
        }
    }

    defaultConfig {
        applicationId = "com.ohmymeme.app"
        minSdk = 28
        targetSdk = 36
        versionCode = 10
        versionName = appVersionName

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("shared")
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("shared")
        }
    }
    buildFeatures {
        aidl = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        val capName = variant.name.replaceFirstChar { it.uppercase() }
        val apkDir = layout.buildDirectory.dir("outputs/apk/${variant.name}")
        val renameTask = tasks.register("rename${capName}Apk") {
            dependsOn("package${capName}")
            doLast {
                val dir = apkDir.get().asFile
                val apk = dir.listFiles { f -> f.isFile && f.extension == "apk" }
                    ?.firstOrNull() ?: return@doLast
                val target = dir.resolve("OhMyMeme-Android-$appVersionName.apk")
                if (!apk.name.equals(target.name)) {
                    apk.renameTo(target)
                }
            }
        }
        tasks.configureEach {
            if (name == "assemble${capName}") {
                dependsOn(renameTask)
            }
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.recyclerview)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.material)
    implementation(libs.xz)
    implementation(libs.androidx.documentfile)
    implementation(libs.shizuku.api)
    implementation(libs.shizuku.provider)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}