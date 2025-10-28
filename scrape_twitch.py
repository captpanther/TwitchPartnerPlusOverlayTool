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

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

async def get_twitch_plus_goal(page):
    js_code = """
    () => {
      const goalsContainer = document.querySelector('.about-section__actions');
      if (!goalsContainer) return null;
      const allGoalWidgets = goalsContainer.querySelectorAll(':scope > div');
      for (const widget of allGoalWidgets) {
        const titleElement = widget.querySelector('h3');
        if (titleElement && titleElement.textContent.trim() === 'Plus Goal') {
          const progressElement = widget.querySelector('strong');
          if (!progressElement) continue;
          const title = titleElement.textContent.trim();
          const progressText = progressElement.textContent.trim();
          let current = null;
          let total = null;
          const parts = progressText.split(' / ');
          if (parts.length === 2) {
            current = parseInt(parts[0].replace(/,/g, ''), 10);
            total = parseInt(parts[1].replace(/,/g, ''), 10);
          }
          return { title, progress: { current, total } };
        }
      }
      return null;
    }
    """
    try:
        return await page.evaluate(js_code)
    except Exception as e:
        print(f"Error evaluating page script: {e}")
        return None

class TwitchScraperApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Twitch Partner Plus Goal Scraper and Overlay Generator")
        self.geometry("500x520")
        
        icon_path = resource_path("icon.ico")
        if sys.platform == "win32" and os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # --- State for persistent browser session ---
        self.playwright_thread = None
        self.playwright_loop = None
        self.browser = None
        self.page = None
        self.current_url = ""
        # -----------------------------------------------

        self.config_file = "config.json"
        self.save_location = os.path.join(os.path.expanduser("~"), "Desktop")
        self.is_running_auto_refresh = False
        self.auto_refresh_job = None
        
        self.grid_columnconfigure(0, weight=1)
        self.channel_entry = ctk.CTkEntry(self, placeholder_text="CaptPanther")
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
        self.start_playwright_thread()

    def start_playwright_thread(self):
        def loop_in_thread(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self.playwright_loop = asyncio.new_event_loop()
        self.playwright_thread = threading.Thread(target=loop_in_thread, args=(self.playwright_loop,), daemon=True)
        self.playwright_thread.start()

    def on_closing(self):
        if self.is_running_auto_refresh:
            self.toggle_auto_refresh()

        config = {
            "channel": self.channel_entry.get(),
            "interval": int(self.interval_slider.get()),
            "save_location": self.save_location,
            "show_percentage": self.show_percentage_switch.get() == 1
        }
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

        if self.playwright_loop and self.playwright_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_shutdown(), self.playwright_loop).result()
            self.playwright_loop.call_soon_threadsafe(self.playwright_loop.stop)
        
        self.destroy()

    async def _async_shutdown(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
    
    async def _async_setup_browser_and_navigate(self, url):
        try:
            if not self.browser:
                p = await async_playwright().start()
                self.browser = await p.chromium.launch(headless=True)
            
            if not self.page:
                self.page = await self.browser.new_page()

            self.after(0, self.update_results_text, f"Navigating to {url}...")
            await self.page.goto(url, wait_until="domcontentloaded")
            
            #await self.page.wait_for_selector('.about-section__actions', timeout=15000)

            self.current_url = url
            return await get_twitch_plus_goal(self.page)
        except Exception as e:
            print(f"Navigation/Wait Error: {e}")
            self.current_url = ""
            return None

    async def _async_scrape_page(self):
        target_url = f'https://www.twitch.tv/{self.channel_entry.get().strip()}/about'
        
        if not self.page or self.current_url != target_url:
            return await self._async_setup_browser_and_navigate(target_url)
        else:
            try:
                return await get_twitch_plus_goal(self.page)
            except Exception as e:
                print(f"Scrape failed, forcing reload: {e}")
                return await self._async_setup_browser_and_navigate(target_url)
    
    def run_scrape(self, is_manual=False):
        channel_name = self.channel_entry.get()
        if not channel_name:
            self.update_ui_with_results(None, "Please enter a channel name.", is_manual)
            if is_manual:
                self.manual_refresh_button.configure(state="normal")
            return

        future = asyncio.run_coroutine_threadsafe(self._async_scrape_page(), self.playwright_loop)
        
        def on_done(f):
            try:
                data = f.result()
                error_msg = None if data else "Widget not yet loaded on page..........Please wait!"
                self.after(0, self.update_ui_with_results, data, error_msg, is_manual)
            except Exception as e:
                error_msg = f"An error occurred: {e}"
                self.after(0, self.update_ui_with_results, None, error_msg, is_manual)
            
            if is_manual:
                self.manual_refresh_button.configure(state="normal")
        
        future.add_done_callback(on_done)
        
    def manual_refresh(self):
        self.update_results_text("Manual Refresh: Starting...")
        self.manual_refresh_button.configure(state="disabled")
        self.run_scrape(is_manual=True)

    def toggle_auto_refresh(self):
        if self.is_running_auto_refresh:
            self.is_running_auto_refresh = False
            if self.auto_refresh_job:
                self.after_cancel(self.auto_refresh_job)
            self.toggle_button.configure(text="Start Auto-Refresh")
            self.set_ui_state_running(False)
        else:
            self.is_running_auto_refresh = True
            self.toggle_button.configure(text="Stop Auto-Refresh")
            self.set_ui_state_running(True)
            self.run_auto_refresh_cycle()

    def run_auto_refresh_cycle(self):
        if not self.is_running_auto_refresh:
            return
        
        self.update_results_text("Auto-Refresh: Checking for updates...")
        self.run_scrape(is_manual=False)
        
        interval_ms = int(self.interval_slider.get()) * 1000
        self.auto_refresh_job = self.after(interval_ms, self.run_auto_refresh_cycle)

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
                default_path = os.path.join(os.path.expanduser("~"), "Desktop")
                self.save_location = config.get("save_location", default_path)
                self.save_path_label.configure(text=f"Save to: {self.save_location}")
                if config.get("show_percentage", True):
                    self.show_percentage_switch.select()
                else:
                    self.show_percentage_switch.deselect()
                    
    def set_ui_state_running(self, is_running):
        state = "disabled" if is_running else "normal"
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
            formatted_result = (f"{refresh_type}: {timestamp}\n\n"
                                f"Title: {title}\n"
                                f"Progress: {current:,} / {total:,}\n"
                                f"Percent Completed: {percent_completed}%")
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
            <html><head><meta http-equiv="refresh" content="5"><style>
            body {{ font-family: Arial, sans-serif; background-color: transparent; color: #FFFFFF; text-shadow: 2px 2px 4px #000000; margin: 0; padding: 10px; overflow: hidden; white-space: nowrap; }}
            .container {{ display: flex; align-items: center; background-color: rgba(0, 0, 0, 0.5); padding: 10px 15px; border-radius: 10px; width: fit-content; }}
            h3 {{ margin: 0; }}
            </style></head><body><div class="container"><h3>{full_text}</h3></div></body></html>
            """
        else:
            message = error_message or "Waiting for data..."
            html_content = f"""<html><head><meta http-equiv="refresh" content="5"></head><body style="font-family: Arial, sans-serif; color: white;"><p>{message}</p></body></html>"""
        file_path = os.path.join(self.save_location, "twitch_plus_goal.html")
        try:
            # --- Ensure the directory exists before writing ---
            os.makedirs(self.save_location, exist_ok=True)
            with open(file_path, "w") as f: f.write(html_content)
        except Exception as e:
            print(f"Error saving browser source file: {e}")
            self.after(0, self.update_results_text, f"Error: Could not save file to\n{self.save_location}")

if __name__ == '__main__':
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("dark-blue")
    app = TwitchScraperApp()
    app.mainloop()