import QtQuick
import QtQuick.Window
import QtWebEngine
import org.kde.plasma.plasmoid
import org.kde.taskmanager as TaskManager

WallpaperItem {
    id: root

    // Com uma janela maximizada ou em tela cheia cobrindo esta tela (na
    // área de trabalho virtual e atividade atuais), a página é escondida:
    // ela se vê oculta e para de desenhar (o Pixel City pausa), poupando
    // CPU, GPU e bateria. Volta assim que a janela sai.
    readonly property bool covered: root.configuration.PauseWhenCovered && tasks.covering > 0
    readonly property rect screenRect: Qt.rect(Screen.virtualX, Screen.virtualY, Screen.width, Screen.height)

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

    WebEngineView {
        id: web

        anchors.fill: parent
        visible: !root.covered
        url: root.configuration.Url
        zoomFactor: root.configuration.Zoom
        backgroundColor: "black"
        audioMuted: true                    // papel de parede não faz barulho
        settings.showScrollBars: false
        settings.focusOnNavigationEnabled: false

        // Perfil em disco (com nome, fora do modo anônimo):
        // o armazenamento da página (o Pixel City guarda ali a qualidade
        // escolhida para este computador) e o cache HTTP sobrevivem ao
        // reinício da sessão, e a página abre mais rápido. (O Qt 6.9 sugere
        // WebEngineProfilePrototype, mas instance() numa ligação chega nulo
        // e derruba o WebEngineView.)
        profile: WebEngineProfile {
            storageName: "webpaper"
            offTheRecord: false
            httpCacheType: WebEngineProfile.DiskHttpCache
        }

        // Sem menu de contexto do navegador sobre a área de trabalho
        onContextMenuRequested: request => request.accepted = true

        // Sem rede no login (ou o site fora do ar): tenta de novo a cada 30 s.
        onLoadingChanged: info => {
            if (info.status === WebEngineView.LoadFailedStatus)
                retry.restart();
        }
    }

    Timer {
        id: retry
        interval: 30000
        onTriggered: web.reload()
    }

    Timer {
        interval: root.configuration.ReloadSeconds * 1000
        running: root.configuration.ReloadSeconds > 0 && !root.covered
        repeat: true
        onTriggered: web.reload()
    }
}
