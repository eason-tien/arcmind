const { app, BrowserWindow, session, systemPreferences } = require('electron');
const path = require('path');
const url = require('url');

// Keep a global reference of the window object, if you don't, the window will
// be closed automatically when the JavaScript object is garbage collected.
let mainWindow;

async function checkMicPermission() {
    if (process.platform === 'darwin') {
        const status = systemPreferences.getMediaAccessStatus('microphone');
        console.log('Current mic status:', status);
        if (status !== 'granted') {
            const success = await systemPreferences.askForMediaAccess('microphone');
            console.log('Mic request result:', success);
        }
    }
}

function createWindow() {
    // Create the browser window.
    mainWindow = new BrowserWindow({
        width: 450,
        height: 800,
        titleBarStyle: 'hiddenInset', // Mac frameless style but keeps traffic lights
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false, // Ease of dev
        }
    });

    // Automatically allow all media permission requests (Mic/Camera) inside chromium session
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
        if (permission === 'media') {
            callback(true); // Always allow microphone!
        } else {
            callback(false);
        }
    });

    // Always grant check permission answers for the device enumerations
    session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
        if (permission === 'media') {
            return true;
        }
        return false;
    });

    const startUrl = process.env.ELECTRON_START_URL || url.format({
        pathname: path.join(__dirname, '../dist/index.html'),
        protocol: 'file:',
        slashes: true
    });

    // Load the index.html of the app.
    mainWindow.loadURL(startUrl);

    // Open the DevTools to see why the screen is black
    mainWindow.webContents.openDevTools();

    // Route renderer console to terminal
    mainWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
        console.log(`[Renderer] ${message} (at ${sourceId}:${line})`);
    });

    // Emitted when the window is closed.
    mainWindow.on('closed', function () {
        // Dereference the window object
        mainWindow = null;
    });
}

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
app.commandLine.appendSwitch('ignore-certificate-errors'); // Helps with HTTP dev
app.whenReady().then(async () => {
    await checkMicPermission();
    createWindow();
});

// Quit when all windows are closed.
app.on('window-all-closed', function () {
    // On OS X it is common for applications and their menu bar
    // to stay active until the user quits explicitly with Cmd + Q
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', function () {
    // On OS X it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (mainWindow === null) {
        createWindow();
    }
});
