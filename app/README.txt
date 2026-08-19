app/
  src/
    core/    ← 功能先看这里（Java）
    ui/      ← 界面（HTML / 图标）
  project/   ← Gradle 工程壳

Build:
  cd project && ./gradlew :app:assembleDebug
