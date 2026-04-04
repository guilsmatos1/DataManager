filepath = "bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/routes.py"
with open(filepath) as f:
    content = f.read()

target = """    for upload_file in files:
        result = await _process_single_html_upload(
            upload_file, magic_number_override, db, parser
        )
        results.append(result)

    return results
"""

idx = content.find(target)
if idx != -1:
    new_content = content[: idx + len(target)]
    with open(filepath, "w") as f:
        f.write(new_content)
    print("Truncated successfully.")
else:
    print("Target not found.")
