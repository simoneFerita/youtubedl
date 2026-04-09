const lookupForm = document.getElementById("lookupForm");
const urlInput = document.getElementById("urlInput");
const searchBtn = document.getElementById("searchBtn");
const formatSelect = document.getElementById("formatSelect");
const formatsSection = document.getElementById("formatsSection");
const videoTitle = document.getElementById("videoTitle");
const statusBox = document.getElementById("status");
const downloadBtn = document.getElementById("downloadBtn");
const API_BASE_PATH = (window.APP_API_BASE_PATH || "").replace(/\/+$/, "");

const state = {
    url: "",
    formats: [],
};

function buildApiUrl(endpoint) {
    const normalized = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
    return `${API_BASE_PATH}${normalized}`;
}

function setStatus(message, type = "info") {
    statusBox.textContent = message;
    statusBox.className = `status ${type}`;
}

function formatBytes(bytes) {
    if (!bytes || Number.isNaN(bytes)) {
        return "dimensione n/d";
    }

    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = bytes;
    let idx = 0;

    while (value >= 1024 && idx < units.length - 1) {
        value /= 1024;
        idx += 1;
    }

    return `${value.toFixed(value < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}

function renderFormatLabel(item) {
    const pieces = [
        item.ext ? item.ext.toUpperCase() : "N/A",
        item.resolution,
        item.kind,
    ];

    if (item.note) {
        pieces.push(item.note);
    }
    if (item.filesize) {
        pieces.push(formatBytes(item.filesize));
    }

    return pieces.join(" • ");
}

function resetFormats() {
    formatSelect.innerHTML = "";
    state.formats = [];
    formatsSection.classList.add("hidden");
}

function parseFilename(dispositionHeader) {
    if (!dispositionHeader) {
        return "";
    }

    const utfMatch = dispositionHeader.match(/filename\*=UTF-8''([^;]+)/i);
    if (utfMatch && utfMatch[1]) {
        return decodeURIComponent(utfMatch[1]);
    }

    const simpleMatch = dispositionHeader.match(/filename=\"?([^\";]+)\"?/i);
    if (simpleMatch && simpleMatch[1]) {
        return simpleMatch[1];
    }

    return "";
}

lookupForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const url = urlInput.value.trim();
    if (!url) {
        setStatus("Inserisci prima un URL.", "error");
        return;
    }

    setStatus("Recupero formati disponibili...", "info");
    searchBtn.disabled = true;
    downloadBtn.disabled = true;
    resetFormats();

    try {
        const response = await fetch(buildApiUrl("/api/formats"), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ url }),
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Errore durante il recupero formati.");
        }

        if (!Array.isArray(data.formats) || data.formats.length === 0) {
            throw new Error("Nessun formato scaricabile trovato per questo URL.");
        }

        state.url = url;
        state.formats = data.formats;
        videoTitle.textContent = data.title || "Contenuto trovato";

        data.formats.forEach((format, index) => {
            const option = document.createElement("option");
            option.value = String(index);
            option.textContent = renderFormatLabel(format);
            formatSelect.appendChild(option);
        });

        formatsSection.classList.remove("hidden");
        downloadBtn.disabled = false;
        setStatus("Scegli un formato e premi Scarica selezionato.", "ok");
    } catch (error) {
        setStatus(error.message, "error");
    } finally {
        searchBtn.disabled = false;
    }
});

downloadBtn.addEventListener("click", async () => {
    if (!state.url || state.formats.length === 0) {
        setStatus("Carica prima i formati.", "error");
        return;
    }

    const selectedIndex = Number(formatSelect.value);
    if (Number.isNaN(selectedIndex) || !state.formats[selectedIndex]) {
        setStatus("Seleziona un formato valido.", "error");
        return;
    }

    const selected = state.formats[selectedIndex];
    setStatus("Download in corso...", "info");
    downloadBtn.disabled = true;

    try {
        const response = await fetch(buildApiUrl("/api/download"), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url: state.url,
                selector: selected.selector,
            }),
        });

        if (!response.ok) {
            const errBody = await response.json().catch(() => ({}));
            throw new Error(errBody.error || "Download fallito.");
        }

        const blob = await response.blob();
        const contentDisposition = response.headers.get("Content-Disposition");
        const filename = parseFilename(contentDisposition) || `download.${selected.ext || "bin"}`;

        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(objectUrl);

        setStatus("Download completato.", "ok");
    } catch (error) {
        setStatus(error.message, "error");
    } finally {
        downloadBtn.disabled = false;
    }
});
