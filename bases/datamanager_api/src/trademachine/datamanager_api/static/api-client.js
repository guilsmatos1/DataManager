/* DataManager Dashboard — API client helper */

async function dmFetch(url, options) {
    options = options || {};
    try {
        const response = await fetch(url, options);
        if (response.redirected) {
            window.location.href = response.url;
            return null;
        }
        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "Request failed: " + response.status);
        }
        return response;
    } catch (err) {
        showToast("Error", err.message, "error");
        return null;
    }
}

async function dmPost(url, formData) {
    return dmFetch(url, { method: "POST", body: formData });
}

async function dmDelete(url) {
    return dmFetch(url, { method: "DELETE" });
}

function formDataFromObj(obj) {
    const fd = new FormData();
    for (const [key, value] of Object.entries(obj)) {
        if (value !== null && value !== undefined && value !== "") {
            fd.append(key, value);
        }
    }
    return fd;
}
