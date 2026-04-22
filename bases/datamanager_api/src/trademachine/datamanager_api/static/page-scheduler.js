/* DataManager Dashboard — Scheduler page */

function showScheduleForm() {
    document.getElementById("schedule-form").style.display = "block";
}

function hideScheduleForm() {
    document.getElementById("schedule-form").style.display = "none";
    // Reset edit state
    document.getElementById("sj-job-id").value = "";
    document.getElementById("sj-source").disabled = false;
    document.getElementById("sj-asset").disabled = false;
    document.getElementById("sj-timeframe").disabled = false;
    document.querySelector("#schedule-form h2").textContent = "Create Scheduled Job";
}

function editJob(jobId, source, asset, timeframe, cron, interval) {
    showScheduleForm();
    document.getElementById("sj-job-id").value = jobId;
    document.getElementById("sj-source").value = source.toLowerCase();
    document.getElementById("sj-asset").value = asset;
    document.getElementById("sj-timeframe").value = timeframe;
    document.getElementById("sj-cron").value = cron;
    document.getElementById("sj-interval").value = interval;
    // Lock identity fields — they define the job_id
    document.getElementById("sj-source").disabled = true;
    document.getElementById("sj-asset").disabled = true;
    document.getElementById("sj-timeframe").disabled = true;
    document.querySelector("#schedule-form h2").textContent = "Edit Scheduled Job";
}

async function submitSchedule(event) {
    event.preventDefault();
    var form = document.getElementById("create-schedule-form");
    var fd = new FormData(form);

    /* Validate: must have interval or cron */
    var interval = fd.get("interval_minutes");
    var cron = fd.get("cron");
    if (!interval && !cron) {
        showToast("Validation Error", "Provide either an interval or a cron expression.", "warning");
        return false;
    }

    var submitBtn = form.querySelector('button[type="submit"]');
    btnLoading(submitBtn);

    var isEdit = !!fd.get("job_id");

    // Disabled fields are excluded from FormData — re-add them for edit
    if (isEdit) {
        fd.set("source", document.getElementById("sj-source").value);
        fd.set("asset", document.getElementById("sj-asset").value);
        fd.set("timeframe", document.getElementById("sj-timeframe").value);
    }

    var resp = await dmPost("/ui/api/schedule", fd);
    btnReset(submitBtn);
    if (resp) {
        var html = await resp.text();
        document.getElementById("schedule-table-body").innerHTML = html;
        showToast(isEdit ? "Job Updated" : "Job Created",
                  isEdit ? "Schedule updated successfully." : "Scheduled job created successfully.",
                  "success");
        hideScheduleForm();
        form.reset();
    }
    return false;
}

function confirmDeleteJob(jobId) {
    showConfirm(
        "Remove Job",
        "Remove scheduled job '" + jobId + "'?",
        function () { doDeleteJob(jobId); }
    );
}

async function doDeleteJob(jobId) {
    var resp = await dmDelete("/ui/api/schedule/" + encodeURIComponent(jobId));
    if (resp) {
        var html = await resp.text();
        document.getElementById("schedule-table-body").innerHTML = html;
        showToast("Job Removed", "Job '" + jobId + "' has been removed.", "success");
    }
}
