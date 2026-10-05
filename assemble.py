"""Combine the template, styles, and data into index.html (the published page)."""
import os, sys
if not os.path.exists("ff_data.json"):
    print("No new data this run (for example, the regular season is over); keeping the current page."); sys.exit(0)
t = open("template.html").read()
assert t.count("__CSS__") == 1 and t.count("__DATA__") == 1
open("index.html", "w").write(t.replace("__CSS__", open("app.css").read()).replace("__DATA__", open("ff_data.json").read()))
print("index.html written")
