const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    // Aquí expondremos las funciones para comunicarse con Python y el sistema
    sendMessage: (channel, data) => ipcRenderer.send(channel, data),
    onMessage: (channel, func) => ipcRenderer.on(channel, (event, ...args) => func(...args)),
});
