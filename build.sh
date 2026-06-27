#!/bin/bash
echo "🚀 Step 1: Compiling Python to Linux Executable..."
pyinstaller --noconsole --onefile --add-data "mainwindow.ui:." --collect-all selenium --name autofeed main.py

echo "📁 Step 2: Creating AppImage Directory Structure..."
rm -rf AppDir
mkdir -p AppDir/usr/bin
cp dist/autofeed AppDir/usr/bin/

echo "⚙️ Step 3: Generating Configuration Files..."
# Create AppRun script
cat << 'EOF' > AppDir/AppRun
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
exec autofeed "$@"
EOF
chmod +x AppDir/AppRun

# Create Desktop file
cat << 'EOF' > AppDir/autofeed.desktop
[Desktop Entry]
Name=Autofeed
Exec=autofeed
Icon=autofeed
Type=Application
Categories=Utility;
EOF

# Generate a valid 1x1 transparent PNG icon so the builder doesn't complain
echo "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==" | base64 -d > AppDir/autofeed.png

echo "📥 Step 4: Downloading AppImage Builder..."
if [ ! -f "appimagetool" ]; then
    wget -q -O appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool
fi

echo "📦 Step 5: Packaging Final AppImage..."
./appimagetool AppDir Autofeed-Linux-x86_64.AppImage

echo "✅ DONE! Your app is ready: Autofeed-Linux-x86_64.AppImage"
