"use strict";

const byId = id => document.getElementById(id);
const value = id => byId(id).value;
const labels = {pending: "Pendiente de moderación", published: "Publicado", hidden: "Oculto"};
const statuses = ["Registrado", "En revisión", "Presentado", "En trámite", "Resuelto", "Cerrado"];
let config = {};
let picker, marker, map, markers;
let routeVersion = 0;

async function api(path, data) {
    if (location.protocol === "file:") {
        throw new Error("Para consultar o registrar reclamos, abrí la plataforma desde el servidor local (python app.py).");
    }
    const options = data === undefined ? {} : {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
    };
    let response;
    try {
        response = await fetch("/api/" + path, options);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "La solicitud falló.");
        return result;
    } catch (error) {
        if (!response || error instanceof SyntaxError) throw new Error("El servidor de reclamos no está disponible.");
        throw error;
    }
}

function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function link(route, text) {
    const anchor = element("a", text, "btn");
    anchor.href = "#" + route;
    return anchor;
}

function card(report) {
    const article = element("article", undefined, "mini");
    article.append(element("h3", report.category), element("p", report.locality),
        element("span", report.status, "status"), document.createElement("br"),
        link("ficha/" + report.id, "Ver reclamo"));
    return article;
}

function leaflet(id) {
    if (!window.L) return null;
    const instance = L.map(id, {scrollWheelZoom: false}).setView([-34.774, -58.635], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(instance);
    return instance;
}

function mapPin() {
    return L.divIcon({className: "rv-pin", iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -10]});
}

function preparePicker() {
    if (!picker) {
        picker = leaflet("rv-picker");
        if (!picker) {
            byId("rv-picker").textContent = "El mapa no está disponible. Podés ingresar las coordenadas.";
            return;
        }
        picker.on("click", event => {
            byId("rv-latitude").value = event.latlng.lat.toFixed(5);
            byId("rv-longitude").value = event.latlng.lng.toFixed(5);
            positionMarker();
        });
    }
    requestAnimationFrame(() => picker.invalidateSize());
}

function positionMarker() {
    if (!picker || !value("rv-latitude") || !value("rv-longitude")) return;
    const point = [Number(value("rv-latitude")), Number(value("rv-longitude"))];
    if (!point.every(Number.isFinite) || Math.abs(point[0]) > 90 || Math.abs(point[1]) > 180) return;
    if (marker) marker.setLatLng(point);
    else marker = L.marker(point, {icon: mapPin(), alt: "Ubicación seleccionada"}).addTo(picker);
}

async function mapReports(version) {
    if (!map) {
        map = leaflet("rv-map");
        if (map) markers = L.layerGroup().addTo(map);
        else byId("rv-map").textContent = "Mapa no disponible. Consultá el listado.";
    }
    if (map) requestAnimationFrame(() => map.invalidateSize());
    const query = new URLSearchParams({locality: value("rv-filter"), category: value("rv-category-filter")});
    const reports = await api("reports?" + query);
    if (version !== routeVersion) return;
    byId("rv-list").replaceChildren(...reports.map(card));
    byId("rv-map-status").textContent = reports.length ? "" : "Todavía no hay reclamos publicados para esta selección.";
    if (!markers) return;
    markers.clearLayers();
    const grouped = new Map();
    for (const report of reports) {
        const point = [report.latitude, report.longitude];
        const key = point.join(",");
        if (!grouped.has(key)) grouped.set(key, {point, reports: []});
        grouped.get(key).reports.push(report);
    }
    for (const group of grouped.values()) {
        const popup = element("div");
        for (const report of group.reports) popup.append(link("ficha/" + report.id, report.category));
        L.marker(group.point, {icon: mapPin(), title: group.reports[0].locality}).addTo(markers).bindPopup(popup);
    }
}

function readFile(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

async function submitReport() {
    const report = byId("form");
    if (!report.reportValidity()) return;
    const submitButton = byId("rv-submit");
    const signature = reportDraftSignature();
    submitButton.disabled = true;
    const output = byId("rv-receipt");
    output.textContent = "Enviando…";
    try {
        const result = await api("reports", {
            category: value("categoria"), locality: value("localidad"),
            place: [value("ubicacion"), value("barrio")].filter(Boolean).join(" · ").slice(0, 180),
            description: value("descripcion"), latitude: Number(value("rv-latitude")),
            longitude: Number(value("rv-longitude")), mode: value("rv-mode"),
            name: value("rv-name"), email: value("rv-email"), consent: byId("rv-consent").checked,
            photos: await Promise.all(files.map(readFile))
        });
        const reference = result.reference || result.id;
        registeredReceipt = {id: reference, signature};
        updateDraftIdentifier();
        const summary = "Número de reclamo: " + reference + (result.reference ? "\nPIN: " : "\nClave privada: ") + result.key;
        const printReceipt = button("Imprimir / guardar comprobante privado");
        printReceipt.onclick = () => {
            byId("print-receipt").replaceChildren(
                element("h2", "Comprobante privado · Reclamos Vecinales"),
                element("p", "Guardá estos datos para consultar el estado desde Seguimiento."),
                element("p", summary, "rv-note"),
                element("p", "Uso personal. El PIN permite consultar el reclamo.")
            );
            document.body.classList.add("print-receipt");
            try {
                window.print();
            } finally {
                document.body.classList.remove("print-receipt");
                byId("print-receipt").replaceChildren();
            }
        };
        const copy = button("Copiar número y PIN");
        copy.onclick = async () => {
            try {
                await navigator.clipboard.writeText(summary);
                copy.textContent = "Copiado";
            } catch {
                const range = document.createRange();
                range.selectNodeContents(credentials);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                copy.textContent = "Datos seleccionados. Presioná Ctrl+C";
            }
        };
        output.textContent = "Reclamo registrado. Guardá el comprobante para consultar el trámite.";
        const credentials = element("p", summary, "rv-note");
        const tracking = button("Ir a seguimiento");
        tracking.onclick = () => {
            const form = byId("rv-track");
            form.elements.id.value = reference;
            form.elements.key.value = result.key;
            go("seguimiento");
        };
        output.append(credentials, copy, printReceipt, tracking);
        const management = byId("rv-management-form");
        management.reset();
        management.elements.id.value = reference;
        management.elements.key.value = result.key;
        management.querySelector('[role="status"]').textContent = "";
        const request = button("Solicitar nuestra gestión");
        request.onclick = openManagement;
        output.append(document.createElement("br"), request);
        byId("rv-name").value = "";
        byId("rv-email").value = "";
        byId("rv-consent").checked = false;
    } catch (error) {
        output.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

function openManagement() {
    const form = byId("rv-management-form");
    form.hidden = false;
    byId("rv-request-management").setAttribute("aria-expanded", "true");
    byId("rv-management").scrollIntoView({block: "center"});
    form.elements.email.focus();
}

function onForm(form, action) {
    form.addEventListener("submit", async event => {
        event.preventDefault();
        const button = form.querySelector('button[type="submit"],button:not([type])');
        const output = form.querySelector('[role="status"]');
        const data = Object.fromEntries(new FormData(form));
        button.disabled = true;
        output.textContent = "Procesando…";
        try {
            output.textContent = await action(data, form);
        } catch (error) {
            output.textContent = error.message;
        } finally {
            button.disabled = false;
        }
    });
}

function field(label, name, initial = "", type = "text", options = []) {
    const wrapper = element("label", label);
    const select = type === "select";
    const input = element(select ? "select" : type === "textarea" ? "textarea" : "input");
    if (select) {
        for (const [key, caption] of options) input.append(new Option(caption, key));
    } else if (input.tagName === "INPUT") {
        input.type = type;
    }
    input.name = name;
    input.value = initial;
    wrapper.append(input);
    return wrapper;
}

function button(text, type = "button") {
    const node = element("button", text, "btn");
    node.type = type;
    return node;
}

function image(id) {
    const node = element("img");
    node.src = "/api/photos/" + id;
    node.alt = "Fotografía del reclamo";
    node.loading = "lazy";
    return node;
}

async function detail(id, version) {
    const output = byId("rv-detail");
    output.textContent = "Cargando…";
    const report = await api("reports/" + encodeURIComponent(id));
    if (version !== routeVersion) return;
    output.replaceChildren(element("h2", report.category),
        element("p", report.locality + " · " + report.place),
        element("p", new Date(report.created * 1000).toLocaleDateString("es-AR")),
        element("span", report.status, "status"), element("p", report.description, "rv-note"));
    const photos = element("div", undefined, "rv-photos");
    photos.append(...report.photos.map(image));
    const count = element("p", "Apoyos verificados: " + report.supports);
    output.append(photos, count, link("mapa", "Volver al mapa"));
    if (!config.verification) {
        output.append(element("p", "La verificación de apoyos se habilitará cuando se configure el correo.", "hint"));
        return;
    }
    const form = element("form", undefined, "rv-form");
    const address = field("Tu correo electrónico", "email", "", "email");
    address.lastChild.required = true;
    const code = field("Código de seis dígitos", "code");
    code.lastChild.required = true;
    code.lastChild.pattern = "[0-9]{6}";
    code.lastChild.inputMode = "numeric";
    const send = button("Pedir código");
    const status = element("p");
    status.setAttribute("role", "status");
    send.onclick = async () => {
        if (!address.lastChild.reportValidity()) return;
        send.disabled = true;
        try {
            await api("code", {email: address.lastChild.value});
            status.textContent = "Código enviado. Revisá tu correo.";
        } catch (error) {
            status.textContent = error.message;
        } finally {
            send.disabled = false;
        }
    };
    form.append(address, send, code, button("Confirmar apoyo", "submit"), status);
    onForm(form, async data => {
        const result = await api("support", {...data, id});
        const current = await api("reports/" + id);
        count.textContent = "Apoyos verificados: " + current.supports;
        form.reset();
        return result.added ? "Apoyo registrado." : "Ya habías apoyado este reclamo.";
    });
    output.append(form);
}

function moderationForm(report) {
    const form = element("form", undefined, "panel rv-form");
    const reportTitle = report.category + " · " + report.locality;
    const photos = element("div", undefined, "rv-photos");
    for (const id of report.photos) {
        const choice = field("Quitar esta foto", "remove_photos", id, "checkbox");
        choice.prepend(image(id));
        photos.append(choice);
    }
    const status = element("p");
    status.setAttribute("role", "status");
    const identity = element("p", report.email ? "Contacto privado: " + report.name + " · " + report.email : "Sin contacto privado");
    form.append(element("h3", reportTitle), element("p", report.reference || report.id, "hint"), identity,
        field("Referencia pública", "place", report.place),
        field("Descripción pública", "description", report.description, "textarea"), photos,
        field("Visibilidad", "visibility", report.visibility, "select", Object.entries(labels)),
        field("Estado del trámite", "status", report.status, "select", statuses.map(s => [s, s])),
        field("Organismo", "agency", report.official_agency),
        field("Expediente oficial", "ref", report.official_ref),
        field("Revisé textos, ubicación y fotografías para excluir datos personales", "reviewed", "yes", "checkbox"),
        button("Guardar revisión", "submit"), status);
    onForm(form, async data => {
        await api("admin/moderate", {...data, id: report.id, reviewed: data.reviewed === "yes",
            remove_photos: new FormData(form).getAll("remove_photos")});
        for (const input of form.querySelectorAll('[name="remove_photos"]:checked')) input.parentElement.remove();
        return "Revisión guardada.";
    });
    if (report.email) {
        const redact = button("Eliminar contacto privado");
        redact.onclick = async () => {
            if (!window.confirm("¿Eliminar el nombre y el correo de este reclamo?")) return;
            try {
                await api("admin/redact", {id: report.id});
                identity.textContent = "Contacto privado eliminado.";
                redact.remove();
            } catch (error) {
                status.textContent = error.message;
            }
        };
        form.append(redact);
    }
    return form;
}

async function admin(version = routeVersion) {
    const output = byId("rv-admin");
    const login = byId("rv-login");
    output.replaceChildren();
    try {
        const data = await api("admin");
        if (version !== routeVersion) return;
        login.hidden = true;
        const exit = button("Cerrar sesión");
        exit.onclick = async () => {
            try {
                await api("admin/logout", {});
                output.replaceChildren();
                login.hidden = false;
            } catch (error) {
                output.prepend(element("p", error.message));
            }
        };
        output.append(exit, element("h3", "Reclamos", "section-title"));
        if (!data.reports.length) output.append(element("p", "Todavía no hay reclamos."));
        output.append(...data.reports.map(moderationForm));
        output.append(element("h3", "Solicitudes de gestión", "section-title"));
        if (!data.management.length) output.append(element("p", "Todavía no hay solicitudes de gestión."));
        for (const item of data.management) {
            const row = element("div", undefined, "mini");
            const done = button(item.handled ? "Atendida" : "Marcar como atendida");
            done.disabled = Boolean(item.handled);
            done.onclick = async () => {
                try {
                    await api("admin/management", {id: item.report});
                    done.disabled = true;
                    done.textContent = "Atendida";
                } catch (error) {
                    row.append(element("p", error.message));
                }
            };
            const remove = button("Eliminar solicitud");
            remove.onclick = async () => {
                if (!window.confirm("¿Eliminar esta solicitud de gestión?")) return;
                try {
                    await api("admin/management", {id: item.report, delete: true});
                    row.remove();
                } catch (error) {
                    row.append(element("p", error.message));
                }
            };
            row.append(element("p", (item.reference || item.report) + " · " + item.email), done, remove);
            output.append(row);
        }
        output.append(element("h3", "Solicitudes de Sumate", "section-title"));
        if (!data.contacts.length) output.append(element("p", "Todavía no hay solicitudes."));
        for (const item of data.contacts) {
            const row = element("div", undefined, "mini");
            const done = button(item.handled ? "Atendida" : "Marcar como atendida");
            done.disabled = Boolean(item.handled);
            done.onclick = async () => {
                try {
                    await api("admin/contact", {id: item.id});
                    done.disabled = true;
                    done.textContent = "Atendida";
                } catch (error) {
                    row.append(element("p", error.message));
                }
            };
            const remove = button("Eliminar solicitud");
            remove.onclick = async () => {
                if (!window.confirm("¿Eliminar esta solicitud de contacto?")) return;
                try {
                    await api("admin/contact", {id: item.id, delete: true});
                    row.remove();
                } catch (error) {
                    row.append(element("p", error.message));
                }
            };
            row.append(element("p", item.locality + " · " + item.email), done, remove);
            output.append(row);
        }
    } catch (error) {
        if (version !== routeVersion) return;
        login.hidden = false;
        login.querySelector('[role="status"]').textContent = error.message;
    }
}

async function route() {
    const version = ++routeVersion;
    if (location.hash === "#guia") history.replaceState(null, "", "#reclamo");
    const [page, id] = (location.hash.slice(1) || "inicio").split("/");
    const resolved = byId("page-" + page) ? page : "inicio";
    byId("nav").classList.remove("open");
    window.scrollTo(0, 0);
    document.querySelectorAll(".page").forEach(node => node.classList.toggle("active", node.id === "page-" + resolved));
    document.querySelectorAll(".nav button").forEach(node => node.classList.toggle("active", node.dataset.page === resolved));
    if (resolved !== "admin") byId("rv-admin").replaceChildren();
    try {
        if (resolved === "reclamo" && !byId("category-section").hidden) preparePicker();
        if (resolved === "mapa") {
            byId("rv-category-filter").value = id === undefined ? "" : (CATS[Number(id)]?.[0] || "");
            await mapReports(version);
        }
        if (resolved === "ficha") await detail(id || "", version);
        if (resolved === "admin") await admin(version);
        if (resolved === "inicio") {
            const reports = await api("reports");
            if (version === routeVersion) byId("rv-recent").replaceChildren(
                ...(reports.length ? reports.slice(0, 2).map(card) : [element("p", "Todavía no hay reclamos publicados.")]));
        }
    } catch (error) {
        const ids = {inicio: "rv-recent", mapa: "rv-map-status", ficha: "rv-detail"};
        if (version === routeVersion && ids[resolved]) byId(ids[resolved]).textContent = error.message;
    }
}

go = page => {
    if (location.hash === "#" + page) route();
    else location.hash = page;
};

for (const locality of LOCS) {
    byId("rv-filter").append(new Option(locality, locality));
    byId("p-localidad").append(new Option(locality, locality));
}

byId("rv-mode").onchange = () => {
    byId("rv-identity").hidden = value("rv-mode") !== "identified";
};
byId("rv-latitude").onchange = byId("rv-longitude").onchange = positionMarker;
for (const [category] of CATS) byId("rv-category-filter").append(new Option(category, category));
byId("rv-filter").onchange = route;
byId("rv-category-filter").onchange = () => {
    const index = categoryIndex(value("rv-category-filter"));
    go(index < 0 ? "mapa" : "mapa/" + index);
};
byId("form").addEventListener("categoryopen", preparePicker);
byId("form").addEventListener("categoryreset", () => {
    if (marker) {
        picker.removeLayer(marker);
        marker = null;
    }
});
byId("rv-submit").onclick = submitReport;
byId("rv-request-management").onclick = openManagement;
byId("form").addEventListener("categoryreset", () => byId("rv-management-form").reset());
onForm(byId("rv-management-form"), async (data, form) => {
    const result = await api("management", {...data, consent: data.consent === "on"});
    form.reset();
    return result.saved ? "Recibimos tu solicitud de gestión." : "Este reclamo ya tiene una solicitud de gestión.";
});

onForm(byId("rv-contact"), async (data, form) => {
    await api("contact", {email: data.email, locality: value("p-localidad"), consent: data.consent === "on"});
    form.reset();
    return "Recibimos tu solicitud de información.";
});
onForm(byId("rv-track"), async data => {
    const result = await api("track", data);
    const history = result.history.map(item =>
        new Date(item.created * 1000).toLocaleDateString("es-AR") + " · " + item.status +
        (item.ref ? " · " + item.agency + " · " + item.ref : "")
    );
    return [labels[result.visibility], result.status,
        result.official_ref ? result.official_agency + " · Expediente " + result.official_ref :
            "Sin expediente oficial registrado.", ...history].join("\n");
});
onForm(byId("rv-login"), async (data, form) => {
    await api("admin/login", data);
    form.reset();
    if (location.hash === "#admin") await admin();
    return "";
});
window.addEventListener("hashchange", route);
api("config").then(result => {
    config = result;
    byId("rv-management-form").querySelector('button[type="submit"]').disabled = !config.management;
    byId("rv-management-privacy").textContent = config.management
        ? config.privacy || "Prueba privada. Usá un correo ficticio."
        : "La recepción de solicitudes de gestión todavía no está habilitada.";
    for (const p of document.querySelectorAll(".rv-privacy")) {
        p.textContent = config.privacy || "La recepción de datos de contacto todavía no está habilitada.";
    }
    byId("rv-mode").querySelector('[value="identified"]').disabled = !config.privacy;
    byId("rv-contact").querySelector("button").disabled = !config.contact;
}).catch(() => {}).finally(route);
