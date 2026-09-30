pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
import QtWebEngine
import org.kde.plasma.plasmoid
import org.kde.taskmanager as TaskManager
import org.kde.kwindowsystem

WallpaperItem {
    id: root

    // While a maximized or full-screen window covers this screen (on the
    // current virtual desktop and activity) the page is hidden: it sees
    // itself hidden and stops drawing (Pixel City pauses), saving CPU, GPU and
    // battery. It comes back when the window goes, or while the desktop is
    // shown (windows are hidden then, not minimized).
    readonly property bool covered: root.configuration.PauseWhenCovered && tasks.covering > 0
        && !KWindowSystem.showingDesktop
    readonly property rect screenRect: Qt.rect(Screen.virtualX, Screen.virtualY, Screen.width, Screen.height)

    // Each wallpaper (one per screen) has its own storage: two profiles with
    // the same name in one process fight over the same files (nothing
    // persists, and one of the pages may not even run). The name is drawn at
    // random the first time and kept in this screen's configuration. If it
    // can't be kept (a Plasma that loaded an older settings schema ignores the
    // key), the page still shows, on a profile for this session only.
    property string sessionId: ""
    readonly property string storageId: root.configuration.StorageId || sessionId

    Component.onCompleted: {
        if (!root.configuration.StorageId) {
            const id = Math.random().toString(36).slice(2, 10);
            root.configuration.StorageId = id;
            root.configuration.writeConfig();   // Q_INVOKABLE; missing from the type info qmllint reads
            if (!root.configuration.StorageId)
                sessionId = id;
        }
    }

    TaskManager.ActivityInfo {
        id: activityInfo
    }

    TaskManager.TasksModel {
        id: tasks

        property int covering: 0

        screenGeometry: root.screenRect
        activity: activityInfo.currentActivity
        filterByScreen: true
        filterByCurrentVirtualDesktop: true
        filterByActivity: true
        filterMinimized: true
        groupMode: TaskManager.TasksModel.GroupDisabled

        function recount() {
            let n = 0;
            for (let i = 0; i < count; i++) {
                const idx = index(i, 0);
                if (data(idx, TaskManager.AbstractTasksModel.IsMaximized) || data(idx, TaskManager.AbstractTasksModel.IsFullScreen))
                    n++;
            }
            covering = n;
        }

        onCountChanged: recount()
        onDataChanged: recount()
        onModelReset: recount()
        Component.onCompleted: recount()
    }

    Loader {
        id: view

        anchors.fill: parent
        active: root.storageId !== ""
        visible: !root.covered

        sourceComponent: WebEngineView {
            url: root.configuration.Url
            zoomFactor: root.configuration.Zoom
            backgroundColor: "black"
            audioMuted: true                    // a wallpaper makes no sound
            settings.showScrollBars: false
            settings.focusOnNavigationEnabled: false
            settings.javascriptCanOpenWindows: false
            settings.navigateOnDropEnabled: false

            // A profile on disk (named, not off the record): the page's storage
            // (where Pixel City keeps the quality tier it chose for this
            // computer) and the HTTP cache survive a session restart, and the
            // page opens faster. (Qt 6.9 suggests WebEngineProfilePrototype,
            // but instance() in a binding comes back null and crashes the
            // WebEngineView.)
            profile: WebEngineProfile {
                storageName: "webpaper-" + root.storageId
                offTheRecord: false
                httpCacheType: WebEngineProfile.DiskHttpCache
            }

            // No browser windows over the desktop: context menu,
            // alert/confirm/prompt, file and color pickers, password prompts,
            // tooltips.
            onContextMenuRequested: request => request.accepted = true
            onJavaScriptDialogRequested: request => { request.accepted = true; request.dialogReject(); }
            onFileDialogRequested: request => { request.accepted = true; request.dialogReject(); }
            onColorDialogRequested: request => { request.accepted = true; request.dialogReject(); }
            onAuthenticationDialogRequested: request => { request.accepted = true; request.dialogReject(); }
            onTooltipRequested: request => request.accepted = true

            // Camera, microphone, location, notifications, screen sharing and
            // the rest: always no (left alone, a request just hangs).
            onPermissionRequested: permission => permission.deny()

            // The page stays on the configured site: navigating to another
            // origin (a link, a script) is refused; redirects go through.
            onNavigationRequested: request => {
                if (!request.isMainFrame || request.navigationType === WebEngineNavigationRequest.RedirectNavigation)
                    return;
                try {
                    if (new URL(request.url).origin !== new URL(root.configuration.Url).origin)
                        request.reject();
                } catch (e) {
                    request.reject();
                }
            }

            // No network at login (or the site down): try again every 30 s.
            onLoadingChanged: info => {
                if (info.status === WebEngineView.LoadFailedStatus)
                    retry.restart();
            }
        }
    }

    Timer {
        id: retry
        interval: 30000
        onTriggered: (view.item as WebEngineView)?.reload()
    }

    Timer {
        interval: root.configuration.ReloadSeconds * 1000
        running: root.configuration.ReloadSeconds > 0 && !root.covered
        repeat: true
        onTriggered: (view.item as WebEngineView)?.reload()
    }
}
