#!/usr/bin/env python3
import os, glob, plistlib, subprocess, shutil, textwrap

def read_plist(path):
    with open(path, 'rb') as f:
        return plistlib.load(f)

def find_loginwindow_plist():
    candidates = []
    # Prefer ByHost first (per-user, per-machine)
    candidates.extend(sorted(glob.glob(os.path.expanduser(
        "~/Library/Preferences/ByHost/com.apple.loginwindow.*.plist"))))
    # Fallback to user-level plist (exists on some systems)
    candidates.append(os.path.expanduser("~/Library/Preferences/com.apple.loginwindow.plist"))
    return [p for p in candidates if os.path.exists(p)]

def app_display_name(app_path, bundle_id):
    # Try mdls for kMDItemDisplayName; fall back to bundle id or basename
    if app_path and os.path.exists(app_path):
        try:
            out = subprocess.check_output(
                ["mdls", "-raw", "-name", "kMDItemDisplayName", app_path],
                stderr=subprocess.DEVNULL, text=True).strip()
            if out and out != "(null)":
                return out
        except Exception:
            pass
        base = os.path.basename(app_path)
        if base.endswith(".app"): 
            return base[:-4]
        return base or (bundle_id or "Unknown")
    return bundle_id or "Unknown"

def decode_bg_state(v):
    mapping = {
        2: "gui-app (relaunch)",
        1: "agent/background",
        0: "unknown"
    }
    return mapping.get(v, "unknown")

def main():
    plists = find_loginwindow_plist()
    if not plists:
        print("No loginwindow plist found.")
        return

    found_any = False
    rows_by_plist = []
    for p in plists:
        try:
            d = read_plist(p)
        except Exception as e:
            continue
        arr = d.get("TALAppsToRelaunchAtLogin", [])
        if not arr:
            continue
        found_any = True
        rows = []
        for item in arr:
            bid = item.get("BundleID", "")
            path = item.get("Path", "")
            hide = item.get("Hide", False)
            bg = item.get("BackgroundState", None)
            name = app_display_name(path, bid)
            rows.append((name, bid, path, hide, bg))
        rows_by_plist.append((p, rows))

    if not found_any:
        print("No apps currently queued to relaunch (you may have unchecked “Reopen windows…” last shutdown).")
        return

    # Pretty print tables
    term = shutil.get_terminal_size((120, 40)).columns
    for p, rows in rows_by_plist:
        print("\nFrom:", p)
        headers = ["App Name", "BundleID", "Hidden", "BackgrndState", "Path"]
        col_widths = [26, 28, 6, 12, max(20, term - (26+28+6+18+8))]
        print("{:<{w0}}  {:<{w1}}  {:<{w2}}  {:<{w3}}  {}".format(
            headers[0], headers[1], headers[2], headers[3], headers[4],
            w0=col_widths[0], w1=col_widths[1], w2=col_widths[2], w3=col_widths[3]))
        print("-" * term)
        for name, bid, path, hide, bg in rows:
            bg_label = decode_bg_state(bg) if bg is not None else "n/a"
            left = "{:<{w0}}  {:<{w1}}  {:<{w2}}  {:<{w3}}  ".format(
                name[:col_widths[0]-1],
                bid[:col_widths[1]-1],
                str(bool(hide))[:col_widths[2]-1],
                (f"{bg} ")[:col_widths[3]-1],
                w0=col_widths[0], w1=col_widths[1], w2=col_widths[2], w3=col_widths[3],
            )
            # Wrap path if long
            if len(path) <= col_widths[4]:
                print(left + path)
            else:
                # wrap path manually
                wrap = textwrap.wrap(path, width=col_widths[4])
                print(left + wrap[0])
                for cont in wrap[1:]:
                    print(" " * (sum(col_widths[:4]) + 8) + cont)

    print("\nLegend for BackgroundState (undocumented, empirical):")
    print("  2 = gui-app (relaunch)")
    print("  1 = agent/background")
    print("  0 or other = unknown/edge-case")

if __name__ == "__main__":
    main()
    print("Also:")
    cmd = "osascript -e 'tell application \"System Events\" to get the name of every login item'"
    print("$", cmd)
    print(subprocess.check_output(cmd, shell=True, text=True).strip())

