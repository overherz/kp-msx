"""Windows launcher for the Media Station X service on the home network."""

import argparse
import ipaddress
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import winreg

import pystray
from PIL import Image, ImageDraw


PORT = 11335
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "KP-MSX")
        return True
    except FileNotFoundError:
        return False


def set_autostart(enabled):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve()))
            command.append("--tray")
            winreg.SetValueEx(key, "KP-MSX", 0, winreg.REG_SZ, subprocess.list2cmdline(command))
        else:
            try:
                winreg.DeleteValue(key, "KP-MSX")
            except FileNotFoundError:
                pass


def tray_image():
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3, 7, 61, 50), radius=8, fill="#174f72", outline="white", width=3)
    draw.polygon([(25, 17), (25, 39), (44, 28)], fill="white")
    draw.line((19, 56, 45, 56), fill="#174f72", width=5)
    return image


def home_address():
    # Prefer a physical LAN adapter over VPN and virtual switch routes.
    script = """
    $ErrorActionPreference = 'Stop'
    $physical = @(Get-NetAdapter -Physical | Where-Object Status -eq Up |
        Select-Object -ExpandProperty ifIndex)
    $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
        Sort-Object @{Expression={ $physical -notcontains $_.InterfaceIndex }},
                    @{Expression={ $_.RouteMetric + $_.InterfaceMetric }}
    foreach ($route in $routes) {
        $ip = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 |
            Where-Object { $_.AddressState -eq 'Preferred' -and !$_.SkipAsSource -and
                           $_.IPAddress -notlike '169.254.*' } |
            Select-Object -First 1 -ExpandProperty IPAddress
        if ($ip) { $ip; break }
    }
    """
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20,
    )
    if result.returncode:
        raise OSError("Не удалось определить адрес сетевого адаптера.")
    output = result.stdout.strip().decode("ascii")
    return str(ipaddress.IPv4Address(output)) if output else None


def serve(messages, stop, override):
    try:
        address = override
        while not address and not stop.is_set():
            address = home_address()
            if not address:
                messages.put(("waiting", None))
                stop.wait(3)
        if stop.is_set():
            return
        data_dir = Path(os.environ["LOCALAPPDATA"]) / "KP-MSX"
        data_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(Path(__file__).resolve().parent)
        os.environ.update(
            MSX_HOST=f"http://{address}:{PORT}",
            RENDER_EXTERNAL_URL="",
            SQLITE_URL=str(data_dir / "devices.sqlite"),
            MONGODB_URL="",
        )
        import uvicorn

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((address, PORT))
            from api import app
            server = uvicorn.Server(uvicorn.Config(
                app, log_config=None, access_log=False, loop="asyncio",
                http="h11", ws="none", lifespan="on",
            ))
            messages.put(("server", (server, address)))
            server.run(sockets=[listener])
    except (Exception, SystemExit) as exc:
        messages.put(("stopped", f"Не удалось запустить сервер. {exc}"))
    else:
        messages.put(("stopped", "Сервер остановлен."))
    finally:
        messages.put(("finished", None))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", type=ipaddress.IPv4Address)
    parser.add_argument("--tray", action="store_true")
    options = parser.parse_args()
    root = tk.Tk()
    root.title("KP-MSX для телевизора")
    root.resizable(False, False)
    if options.tray:
        root.withdraw()
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Подключение Media Station X", font=("Segoe UI", 16)).pack(anchor="w")
    status = tk.StringVar(value="Определяем адрес компьютера и запускаем сервер…")
    messages = queue.Queue()
    stop = threading.Event()
    server = None
    address = None
    running = True
    closing = False
    tray_ready = False
    startup = tk.BooleanVar(value=autostart_enabled())

    def show():
        root.deiconify()
        root.lift()

    def toggle_startup():
        try:
            set_autostart(startup.get())
        except (OSError, ValueError) as exc:
            show()
            messagebox.showerror("Автозапуск KP-MSX", str(exc), parent=root)
        startup.set(autostart_enabled())
        tray.update_menu()

    def minimize(event):
        if event.widget == root and tray_ready and root.state() == "iconic":
            root.after_idle(root.withdraw)

    def poll():
        nonlocal server, address, running, tray_ready
        while not messages.empty():
            event, value = messages.get_nowait()
            if event == "server":
                server, address = value
            elif event == "waiting":
                status.set("Ожидание подключения к домашней сети…")
            elif event == "finished":
                running = False
            elif event == "ready":
                tray_ready = True
            elif event == "show":
                show()
            elif event == "exit":
                close()
            elif event == "startup":
                startup.set(not autostart_enabled())
                toggle_startup()
            else:
                server = None
                status.set(value)
                if not closing:
                    show()
        if closing:
            if not running:
                tray.stop()
                root.destroy()
                return
            if server and server.started:
                server.should_exit = True
        elif server and server.started:
            status.set(f"В Start Parameter на телевизоре введите   {address}:{PORT}\n"
                       "Окно можно свернуть в область уведомлений.")
        root.after(150, poll)

    def close():
        nonlocal closing
        closing = True
        stop.set()
        status.set("Остановка…")

    ttk.Label(frame, textvariable=status, wraplength=440, width=60).pack(anchor="w", pady=(12, 0))
    startup_label = "Запускать при входе в Windows"
    menu = tk.Menu(root)
    settings = tk.Menu(menu, tearoff=False)
    settings.add_checkbutton(label=startup_label, variable=startup, command=toggle_startup)
    settings.add_separator()
    settings.add_command(label="Выход", command=close)
    menu.add_cascade(label="Приложение", menu=settings)
    root.configure(menu=menu)

    def tray_command(event):
        return lambda: messages.put((event, None))

    tray = pystray.Icon("KP-MSX", tray_image(), "KP-MSX для телевизора", pystray.Menu(
        pystray.MenuItem("Открыть", tray_command("show"), default=True),
        pystray.MenuItem(startup_label, tray_command("startup"), checked=lambda item: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", tray_command("exit")),
    ))

    def setup(icon):
        icon.visible = True
        messages.put(("ready", None))

    tray.run_detached(setup=setup)
    root.bind("<Unmap>", minimize)
    root.protocol("WM_DELETE_WINDOW", lambda: root.withdraw() if tray_ready else close())
    # Older Run entries included the IP from the previous Windows session.
    override = str(options.address) if options.address and not options.tray else None
    threading.Thread(target=serve, args=(messages, stop, override), daemon=True).start()
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
