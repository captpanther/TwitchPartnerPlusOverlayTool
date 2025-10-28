import asyncio
import json
import threading
import customtkinter as ctk
from customtkinter import filedialog
from playwright.async_api import async_playwright
import os
import sys
import math
import time
from datetime import datetime

# --- HELPER FUNCTIONS FOR PACKAGING ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def find_playwright_chromium():
    """Dynamically finds the Playwright browser path for the current OS."""
    if sys.platform == "darwin": # macOS
        playwright_path = os.path.join(os.path.expanduser('~'), 'Library', 'Caches', 'ms-playwright')
        executable_subpath = os.path.join('chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium')
    elif sys.platform.startswith("linux"): # Linux
        playwright_path = os.path.join(os.path.expanduser('~'), '.cache', 'ms-playwright')
        executable_subpath = os.path.join('chrome-linux', 'chrome')
    else:
        playwright_path = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'ms-playwright')
        executable_subpath = os.path.join('chrome-win', 'chrome.exe')

    if not os.path.exists(playwright_path):
        return None

    # Find the latest chromium folder (e.g., 'chromium-1091')
    chromium_folders = [f for f in os.listdir(playwright_path) if f.startswith('chromium-')]
    if not chromium_folders:
        return None
    latest_chromium_folder = sorted(chromium_folders, reverse=True)[0]

    # Construct the full path to the executable
    executable_path = os.path.join(playwright_path, latest_chromium_folder, 'chrome-win', 'chrome.exe')
    
    # Return the folder to be bundled and the executable path within it
    if os.path.exists(executable_path):
        return (os.path.join(playwright_path, latest_chromium_folder), executable_path)
    return None
# ------------------------------------

async def get_twitch_plus_goal(twitch_channel_url: str, bundled_executable_path: str) -> dict | None:
    if not twitch_channel_url:
        print("❌ Error: A Twitch URL is required.")
        return None

    async with async_playwright() as p:
        browser = None
        try:
            # When packaged, sys.frozen is true. Use the bundled browser.
            # Otherwise (in development), let Playwright find the browser.
            executable_path_to_use = resource_path(os.path.join("chromium", "chrome-win", "chrome.exe")) if getattr(sys, 'frozen', False) else None
            
            browser = await p.chromium.launch(executable_path=executable_path_to_use)
            
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            page = await context.new_page()
            await page.goto(twitch_channel_url, wait_until="networkidle", timeout=60000)

            js_code = """
            () => {
              const goalsContainer = document.querySelector('.about-section__actions');
              if (!goalsContainer) return null;
              const allGoalWidgets = goalsContainer.querySelectorAll(':scope > div');
              for (const widget of allGoalWidgets) {
                const titleElement = widget.querySelector('h3');
                if (titleElement && titleElement.textContent.trim() === 'Plus Goal') {
                  const progressElement = widget.querySelector('strong');
                  const labelElement = widget.querySelector('span');
                  const title = titleElement.textContent.trim();
                  const progressText = progressElement ? progressElement.textContent.trim() : null;
                  const label = labelElement ? labelElement.textContent.trim() : null;
                  if (!progressText) return null;
                  let current = null;
                  let total = null;
                  const parts = progressText.split(' / ');
                  if (parts.length === 2) {
                    current = parseInt(parts[0].replace(/,/g, ''), 10);
                    total = parseInt(parts[1].replace(/,/g, ''), 10);
                  }
                  return { title, label, progress: { current, total } };
                }
              }
              return null;
            }
            """
            goal_data = await page.evaluate(js_code)
            return goal_data
        except Exception as e:
            print(f"An error occurred during the scraping process: {e}")
            return None
        finally:
            if browser:
                await browser.close()

class TwitchScraperApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Twitch Partner Plus Goal Scraper and Overlay Generator")
        self.geometry("500x520")
        
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.config_file = "config.json"
        self.save_location = os.getcwd()
        self.is_running = False
        self.scraping_thread = None
        self.grid_columnconfigure(0, weight=1)
        self.channel_entry = ctk.CTkEntry(self, placeholder_text="Enter Twitch Channel Name")
        self.channel_entry.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="ew")
        self.slider_label = ctk.CTkLabel(self, text="Refresh Interval: 30s")
        self.slider_label.grid(row=1, column=0, padx=(20, 10), pady=10, sticky="w")
        self.interval_slider = ctk.CTkSlider(self, from_=5, to=120, number_of_steps=23, command=self.update_slider_label)
        self.interval_slider.grid(row=1, column=1, padx=(10, 20), pady=10, sticky="ew")
        self.save_path_label = ctk.CTkLabel(self, text=f"Save to: {self.save_location}", anchor="w", justify="left")
        self.save_path_label.grid(row=2, column=0, padx=(20, 10), pady=10, sticky="ew")
        self.browse_button = ctk.CTkButton(self, text="Browse...", command=self.select_save_location)
        self.browse_button.grid(row=2, column=1, padx=(10, 20), pady=10, sticky="e")
        self.options_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.options_frame.grid(row=3, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.options_frame.grid_columnconfigure(0, weight=1)
        self.show_percentage_switch = ctk.CTkSwitch(self.options_frame, text="Show Percentage in Overlay")
        self.show_percentage_switch.grid(row=0, column=0, sticky="w")
        self.show_percentage_switch.select()
        self.manual_refresh_button = ctk.CTkButton(self.options_frame, text="Manual Refresh", command=self.manual_refresh)
        self.manual_refresh_button.grid(row=0, column=1, sticky="e")
        self.toggle_button = ctk.CTkButton(self, text="Start Auto-Refresh", command=self.toggle_auto_refresh)
        self.toggle_button.grid(row=4, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.result_textbox = ctk.CTkTextbox(self, wrap="word")
        self.result_textbox.grid(row=5, column=0, columnspan=2, padx=20, pady=(10, 20), sticky="nsew")
        self.grid_rowconfigure(5, weight=1)
        self.load_settings()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def select_save_location(self):
        directory = filedialog.askdirectory()
        if directory:
            self.save_location = directory
            self.save_path_label.configure(text=f"Save to: {self.save_location}")

    def update_slider_label(self, value):
        val = int(value)
        self.slider_label.configure(text=f"Refresh Interval: {val}s")

    def load_settings(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                config = json.load(f)
                self.channel_entry.insert(0, config.get("channel", ""))
                interval = config.get("interval", 30)
                self.interval_slider.set(interval)
                self.update_slider_label(interval)
                self.save_location = config.get("save_location", os.getcwd())
                self.save_path_label.configure(text=f"Save to: {self.save_location}")
                if config.get("show_percentage", True):
                    self.show_percentage_switch.select()
                else:
                    self.show_percentage_switch.deselect()

    def on_closing(self):
        self.is_running = False 
        config = {
            "channel": self.channel_entry.get(),
            "interval": int(self.interval_slider.get()),
            "save_location": self.save_location,
            "show_percentage": self.show_percentage_switch.get() == 1
        }
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)
        self.destroy()

    def manual_refresh(self):
        self.manual_refresh_button.configure(state="normal")
        manual_thread = threading.Thread(target=self.run_single_scrape, daemon=True)
        manual_thread.start()

    def run_single_scrape(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        channel_name = self.channel_entry.get()
        if not channel_name:
            self.after(0, self.update_ui_with_results, None, "Please enter a channel name.", True)
            self.after(0, self.manual_refresh_button.configure, {"state": "normal"})
            return
        self.after(0, self.update_results_text, f"Manual Refresh: Scraping {channel_name}...")
        channel_url = f'https://www.twitch.tv/{channel_name.strip()}/about'
        data = loop.run_until_complete(get_twitch_plus_goal(channel_url, ""))
        error_msg = None if data else "Failed to scrape data or no 'Plus Goal' widget found."
        self.after(0, self.update_ui_with_results, data, error_msg, True)
        self.after(0, self.manual_refresh_button.configure, {"state": "normal"})

    def toggle_auto_refresh(self):
        if self.is_running:
            self.is_running = False
            self.toggle_button.configure(text="Stopping...", state="disabled")
        else:
            self.is_running = True
            self.set_ui_state_running(True)
            self.scraping_thread = threading.Thread(target=self.run_auto_refresh_logic, daemon=True)
            self.scraping_thread.start()

    def run_auto_refresh_logic(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self.is_running:
            channel_name = self.channel_entry.get()
            if not channel_name:
                self.after(0, self.update_ui_with_results, None, "Please enter a channel name.", False)
                break 
            self.after(0, self.update_results_text, f"Auto-Refresh: Scraping {channel_name}...")
            channel_url = f'https://www.twitch.tv/{channel_name}/about'
            data = loop.run_until_complete(get_twitch_plus_goal(channel_url, ""))
            error_msg = None if data else "Failed to scrape data or no 'Plus Goal' widget found."
            self.after(0, self.update_ui_with_results, data, error_msg, False)
            for _ in range(int(self.interval_slider.get())):
                if not self.is_running:
                    break
                time.sleep(1)
        self.after(0, self.set_ui_state_running, False)

    def set_ui_state_running(self, is_running):
        state = "disabled" if is_running else "normal"
        if is_running:
            self.toggle_button.configure(text="Stop Auto-Refresh")
        else:
            self.toggle_button.configure(text="Start Auto-Refresh", state="normal")
        self.channel_entry.configure(state=state)
        self.interval_slider.configure(state=state)
        self.browse_button.configure(state=state)
        self.show_percentage_switch.configure(state=state)

    def update_ui_with_results(self, data, error_message=None, is_manual=False):
        timestamp = datetime.now().strftime("%I:%M:%S %p")
        refresh_type = "Manual Refresh" if is_manual else "Last Refreshed"
        if data and data.get("title"):
            title = data['title']
            current = data['progress']['current']
            total = data['progress']['total']
            percent_completed = math.floor((int(current) / int(total)) * 100) if total > 0 else 0
            formatted_result = (
                f"{refresh_type}: {timestamp}\n\n"
                f"Title: {title}\n"
                f"Progress: {current:,} / {total:,}\n"
                f"Percent Completed: {percent_completed}%"
            )
            self.update_results_text(formatted_result)
            self.generate_browser_source_html(data)
        else:
            error_text = error_message or "An unknown error occurred."
            refresh_source = 'Manual' if is_manual else 'Auto'
            formatted_error = f"Last Attempt ({refresh_source}): {timestamp}\n\n{error_text}"
            self.update_results_text(formatted_error)
            self.generate_browser_source_html(None, error_message)

    def update_results_text(self, message):
        self.result_textbox.delete("1.0", "end")
        self.result_textbox.insert("1.0", message)

    def generate_browser_source_html(self, data, error_message=None):
        if data:
            title = data['title']
            current = data['progress']['current']
            total = data['progress']['total']
            progress_text = f"{current:,} / {total:,}"
            if self.show_percentage_switch.get() == 1:
                percent = math.floor((int(current) / int(total)) * 100) if total > 0 else 0
                progress_text += f" ({percent}%)"
            full_text = f"{title}: {progress_text}"
            html_content = f"""
            <html>
            <head>
                <meta http-equiv="refresh" content="5">
                <style>
                    body {{
                        font-family: Arial, sans-serif; background-color: transparent;
                        color: #FFFFFF; text-shadow: 2px 2px 4px #000000;
                        margin: 0; padding: 10px; overflow: hidden; white-space: nowrap;
                    }}
                    .container {{
                        display: flex; align-items: center;
                        background-color: rgba(0, 0, 0, 0.5);
                        padding: 10px 15px; border-radius: 10px;
                        width: fit-content;
                    }}
                    h3 {{ margin: 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h3>{full_text}</h3>
                </div>
            </body>
            </html>
            """
        else:
            message = error_message or "Waiting for data..."
            html_content = f"""
            <html><head><meta http-equiv="refresh" content="5"></head>
            <body style="font-family: Arial, sans-serif; color: white;"><p>{message}</p></body></html>
            """
        file_path = os.path.join(self.save_location, "twitch_plus_goal.html")
        try:
            with open(file_path, "w") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Error saving browser source file: {e}")
            self.after(0, self.update_results_text, f"Error: Could not save file to\n{self.save_location}")

if __name__ == '__main__':
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("dark-blue")
    app = TwitchScraperApp()
    app.mainloop()