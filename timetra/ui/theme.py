from tkinter import ttk

LIGHT = {
    "bg": "#F2F6F4", "surface": "#FFFFFF", "border": "#D3DEDA", "text": "#1E2A27", "muted": "#56665F",
    "accent": "#0F6E5C", "on_accent": "#FFFFFF", "accent_soft": "#DCEDE8", "hover": "#E8F0ED",
    "conflict": "#B83A3A", "conflict_soft": "#F9E7E6", "warn": "#8F5B00", "warn_soft": "#F6ECD6",
    "ok": "#2C7A3F", "ok_soft": "#E1F0E4", "tip_bg": "#1E2A27", "tip_fg": "#F2F6F4",
}
DARK = {
    "bg": "#16211E", "surface": "#1F2D29", "border": "#35463F", "text": "#E6EEEA", "muted": "#9FB0A9",
    "accent": "#5FCFB4", "on_accent": "#0D2420", "accent_soft": "#24413A", "hover": "#29392F",
    "conflict": "#F28B82", "conflict_soft": "#3E2624", "warn": "#E3B552", "warn_soft": "#3A3120",
    "ok": "#86D08F", "ok_soft": "#223A2A", "tip_bg": "#E6EEEA", "tip_fg": "#16211E",
}

colors = dict(LIGHT)
_big = False


def system_prefers_dark() -> bool:
    import winreg

    key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def font(size=10, bold=False):
    if _big:
        size += 2
    return ("Segoe UI", size, "bold") if bold else ("Segoe UI", size)


def icon_font(size=11):
    # шрифт значков есть в любой Windows 10+, поэтому в сборку не нужно класть картинки
    return ("Segoe MDL2 Assets", size + 2 if _big else size)


def apply_theme(root, theme: str, big_text: bool) -> None:
    global _big
    _big = big_text
    dark = theme == "dark" or (theme == "system" and system_prefers_dark())
    colors.update(DARK if dark else LIGHT)
    c = colors
    root.configure(bg=c["bg"])
    root.option_add("*TCombobox*Listbox.background", c["surface"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["on_accent"])
    root.option_add("*TCombobox*Listbox.font", font())
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "TCombobox", fieldbackground=c["surface"], background=c["surface"], foreground=c["text"],
        arrowcolor=c["text"], bordercolor=c["border"], lightcolor=c["surface"], darkcolor=c["surface"], padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", c["surface"])], foreground=[("readonly", c["text"])],
        selectbackground=[("readonly", c["surface"])], selectforeground=[("readonly", c["text"])],
    )
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            name, background=c["border"], troughcolor=c["bg"], bordercolor=c["bg"],
            arrowcolor=c["muted"], lightcolor=c["border"], darkcolor=c["border"],
        )
        style.map(name, background=[("active", c["muted"])])
