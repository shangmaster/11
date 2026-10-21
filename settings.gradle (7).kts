pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
        // Xposed API 在 jcenter 停服后靠这个仓库，或者用下面的本地 jar 方案
        maven("https://api.xposed.info/")
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven("https://api.xposed.info/")
    }
}
rootProject.name = "CxSignHook"
include(":app")
