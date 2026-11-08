#!/usr/bin/env python3
"""BetterFrame Settings (first working version): Steam's, SteamVR's and BetterFrame's settings on one page.

    python3 bfsettings.py            serve the page on http://localhost:8644
    python3 bfsettings.py list       print every setting and its value now

Every change goes through the same calls Steam's and SteamVR's own settings pages use."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dashpin  # noqa: E402

PORT = 8644


def _lang_options():
    """Every keyboard language, in its own name (with its version when it has more than one: English (US), English (UK))."""
    try:
        import languages as L
        out = []
        groups = L.groups()
        # English first, then Japanese (lots of Frame players type it), then the rest in their usual order
        groups = sorted(groups, key=lambda g: {"en": 0, "ja": 1}.get(g[0], 2))
        for _, name, ls in groups:
            for l in ls:
                out.append([l["code"], name if len(ls) == 1 else "%s (%s)" % (name, L.variant_label(l))])
        return out or [["en-US", "English (US)"]]
    except Exception:
        return [["en-US", "English (US)"]]

# id, category, section, label, kind (switch/slider/choice/info), where, setting path (SteamVR) or read code (Steam),
# extra: scale (shown = stored x scale), min/max/step/unit, options
S = [
    # ---- Display
    ("brightness", "Display", "Picture", "Brightness", "slider", "vr", "/settings/steamvr/analogGain",
     {"scale": 100, "min": 30, "max": 100, "step": 1, "unit": "%"}),
    ("refresh", "Display", "Picture", "Refresh rate", "choice", "vr", "/settings/steamvr/preferredRefreshRate",
     {"options": [[72, "72 Hz"], [90, "90 Hz"], [120, "120 Hz"], [144, "144 Hz"]]}),
    ("smoothing", "Display", "Picture", "Motion smoothing", "switch", "vr", "/settings/steamvr/motionSmoothing", {}),
    ("curvature", "Windows", "Menus", "Curved menus and windows", "switch", "vr", "/settings/dashboard/allowCurvature", {}),
    # ---- Sound
    ("noise", "Sound", "Microphone", "Noise suppression", "switch", "vr", "/settings/dashboard/enableMicNoiseSuppression", {}),
    ("echo", "Sound", "Microphone", "Echo cancellation", "switch", "vr", "/settings/dashboard/enableMicEchoCancellation", {}),
    # ---- Controls
    ("laser", "Controls", "Laser", "Laser width (after SteamVR restarts)", "slider", "vr", "/settings/dashboard/laserRayWidthScale",
     {"scale": 100, "min": 30, "max": 150, "step": 5, "unit": "%"}),
    ("ctrloff", "Controls", "Controllers", "Turn controllers off when idle", "choice", "vr", "/settings/power/turnOffControllersTimeout",
     {"options": [[60, "1 minute"], [300, "5 minutes"], [900, "15 minutes"], [1800, "30 minutes"]]}),
    ("ss_manual", "Display", "Resolution", "Set resolution by hand", "switch", "vr", "/settings/steamvr/supersampleManualOverride", {}),
    ("ss_scale", "Display", "Resolution", "Resolution scale (when set by hand)", "slider", "vr", "/settings/steamvr/supersampleScale",
     {"scale": 100, "min": 50, "max": 200, "step": 5, "unit": "%"}),
    ("sharpen", "Display", "Picture", "Sharpening", "switch", "vr", "/settings/steamvr/sharpening", {}),
    ("profile", "Display", "Performance", "Performance profile", "choice", "vr", "/settings/steamvr/performanceProfile",
     {"options": [["Performance", "Performance"], ["Powersave", "Power saving"]]}),
    ("ps_refresh", "Display", "Performance", "Refresh rate when power saving", "choice", "vr", "/settings/steamvr/powersaveRefreshRate",
     {"options": [[72, "72 Hz"], [90, "90 Hz"], [120, "120 Hz"]]}),
    ("theater_dist", "Windows", "Theater and desktop", "Theater screen distance", "slider", "vr", "/settings/dashboard/defaultTheaterDistance",
     {"scale": 10, "min": 10, "max": 80, "step": 1, "unit": " m", "div": 10}),
    ("theater_size", "Windows", "Theater and desktop", "Theater screen size", "slider", "vr", "/settings/dashboard/defaultTheaterScale",
     {"scale": 10, "min": 10, "max": 60, "step": 1, "unit": "x", "div": 10}),
    ("theater_auto", "Windows", "Theater and desktop", "Show games in theater automatically", "switch", "vr", "/settings/dashboard/autoShowGameTheater", {}),
    ("desk_scale", "Windows", "Theater and desktop", "Desktop window size", "slider", "vr", "/settings/dashboard/desktopScale",
     {"scale": 100, "min": 50, "max": 200, "step": 5, "unit": "%"}),
    ("menu_on_exit", "Windows", "Menus", "Open the menu when a game closes", "switch", "vr", "/settings/dashboard/showOnAppExit", {}),
    ("cursor", "Controls", "Laser", "Pointer size", "slider", "vr", "/settings/dashboard/cursorScale",
     {"scale": 100, "min": 50, "max": 200, "step": 10, "unit": "%"}),
    ("laser_hide", "Controls", "Laser", "Hide the laser after (seconds)", "slider", "vr", "/settings/steamvr/laserMouseAutoHideTimeout",
     {"scale": 1, "min": 2, "max": 30, "step": 1}),
    ("deadzone", "Controls", "Controllers", "Thumbstick dead zone", "slider", "vr", "/settings/input/thumbstickDeadzone",
     {"scale": 100, "min": 0, "max": 50, "step": 1, "unit": "%"}),
    ("screens_off", "Power", "Sleep", "Screens off after taking the headset off (minutes)", "slider", "vr", "/settings/power/turnOffScreensTimeout",
     {"scale": 1, "min": 1, "max": 30, "step": 1}),
    ("pause_standby", "Power", "Sleep", "Pause the view when the headset is off", "switch", "vr", "/settings/power/pauseCompositorOnStandby", {}),
    ("bounds_fade", "Play Area", "Boundary", "Show the boundary from (metres away)", "slider", "vr",
     "/settings/collisionBounds/CollisionBoundsFadeDistance", {"scale": 100, "min": 20, "max": 200, "step": 10, "unit": " cm"}),
    ("bounds_floor", "Play Area", "Boundary", "Show the boundary on the floor", "switch", "vr",
     "/settings/collisionBounds/CollisionBoundsGroundPerimeterOn", {}),
    ("floor", "Play Area", "Boundary", "Show the floor", "switch", "vr", "/settings/steamvr/showFloor", {}),
    ("mirror", "Sound", "Speakers", "Also play sound on a PC", "switch", "vr", "/settings/audio/enablePlaybackMirror", {}),
    # ---- People
    ("dnd", "People", "Menus", "Do not disturb (SteamVR's)", "switch", "vr", "/settings/notifications/DoNotDisturb", {}),
    ("shots", "People", "Menus", "Screenshots", "switch", "vr", "/settings/userinterface/screenshots", {}),
    # ---- System (Steam)
    ("language", "System", "Language and time", "Language", "info", "steam", "SteamClient.Settings.GetCurrentLanguage()", {}),
    ("timezone", "System", "Language and time", "Time zone", "info", "steam", "SteamClient.Settings.GetTimeZone()", {}),
    # ---- Steam's own settings (key in its settings store; "sc" = client setting, "sf" = friends setting)
    ("sc_ui_sounds", "Sound", "Sounds", "Menu sounds", "switch", "sc", "enable_ui_sounds", {}),
    ("sc_toast_sound", "Sound", "Sounds", "Notification sound", "switch", "sc", "play_sound_on_toast", {}),
    ("sc_ach_sound", "Sound", "Sounds", "Achievement sound", "switch", "sc", "achievement_notification_sound", {}),
    ("sc_shot_sound", "Sound", "Sounds", "Screenshot sound", "switch", "sc", "enable_screenshot_sound", {}),
    ("sc_voice_out", "Sound", "Voice chat", "Voice chat volume", "slider", "sc", "voice_speaker_output_gain",
     {"scale": 100, "min": 0, "max": 100, "step": 5, "unit": "%"}),
    ("sc_voice_in", "Sound", "Voice chat", "Voice chat mic level", "slider", "sc", "voice_mic_input_gain",
     {"scale": 100, "min": 0, "max": 300, "step": 10, "unit": "%"}),
    ("sc_mono", "Sound", "Voice chat", "Mono audio", "switch", "sc", "accessibility_mono_audio", {}),
    ("sc_no_toasts", "People", "Notifications", "Turn off all pop-ups", "switch", "sc", "disable_all_toasts", {}),
    ("sc_no_toasts_game", "People", "Notifications", "No pop-ups while playing", "switch", "sc", "disable_toasts_in_game", {}),
    ("sc_ach_toast", "People", "Notifications", "Achievement pop-ups", "switch", "sc", "achievement_notification_toast", {}),
    ("sc_shot_toast", "People", "Notifications", "Screenshot pop-ups", "switch", "sc", "enable_screenshot_notification", {}),
    ("sc_ctrl_toast", "People", "Notifications", "Controller connected pop-ups", "switch", "sc", "controllerconnect_notification_toast", {}),
    ("sc_lowbat_toast", "People", "Notifications", "Controller low battery pop-ups", "switch", "sc", "controller_low_battery_notification_toast", {}),
    ("sc_family_toast", "People", "Notifications", "Family sharing pop-ups", "switch", "sc", "show_family_sharing_notifications", {}),
    ("sc_marketing", "People", "Notifications", "Sale and marketing messages", "switch", "sc", "enable_marketing_messages", {}),
    ("sf_msg", "People", "Friends", "Message pop-ups", "switch", "sf", "bNotifications_ShowMessage", {}),
    ("sf_msg_sound", "People", "Friends", "Message sound", "switch", "sf", "bSounds_PlayMessage", {}),
    ("sf_online", "People", "Friends", "Pop-up when a friend comes online", "switch", "sf", "bNotifications_ShowOnline", {}),
    ("sf_ingame", "People", "Friends", "Pop-up when a friend starts a game", "switch", "sf", "bNotifications_ShowIngame", {}),
    ("sf_dnd", "People", "Friends", "Do not disturb (friends)", "switch", "sf", "bDoNotDisturbMode", {}),
    ("sf_avatars", "People", "Friends", "Animated profile pictures", "switch", "sf", "bAnimatedAvatars", {}),
    ("sf_signin", "People", "Friends", "Sign in to Friends at startup", "switch", "sf", "bSignIntoFriends", {}),
    ("sc_dl_playing", "Games", "Downloads", "Download while playing", "switch", "sc", "download_while_app_running", {}),
    ("sc_dl_stream", "Games", "Downloads", "Slow downloads while streaming", "switch", "sc", "download_throttle_while_streaming", {}),
    ("sc_dl_asleep", "Games", "Downloads", "Download while asleep", "switch", "sc", "system_enable_low_power_downloads", {}),
    ("sc_restrict", "Games", "Downloads", "Only update games at set times", "switch", "sc", "restrict_auto_updates", {}),
    ("sc_cloud", "Games", "Saves", "Steam Cloud", "switch", "sc", "cloud_enabled", {}),
    ("sc_precache", "Games", "Shaders", "Shader pre-caching", "switch", "sc", "enable_shader_precache", {}),
    ("sc_shader_bg", "Games", "Shaders", "Process shaders in the background", "switch", "sc", "enable_shader_background_processing", {}),
    ("sc_overlay", "Games", "In game", "Steam overlay in games", "switch", "sc", "enable_overlay", {}),
    ("sc_rec_fps", "Games", "Recording", "Recording frame rate", "choice", "sc", "gamerecording_max_fps",
     {"options": [[30, "30 fps"], [60, "60 fps"]]}),
    ("sc_raw_shots", "Games", "Recording", "Also save uncompressed screenshots", "switch", "sc", "save_uncompressed_screenshots", {}),
    ("sc_store_home", "Games", "Library", "Store content on Home", "switch", "sc", "show_store_content_on_home", {}),
    ("sc_lowperf", "Games", "Library", "Low performance mode for the library", "switch", "sc", "library_low_perf_mode", {}),
    ("sc_lowbw", "Games", "Library", "Low bandwidth mode", "switch", "sc", "library_low_bandwidth_mode", {}),
    ("sc_nocommunity", "Games", "Library", "Hide community content", "switch", "sc", "library_disable_community_content", {}),
    ("sc_streaming_ready", "Games", "Library", "Count games you can stream as ready to play", "switch", "sc", "ready_to_play_includes_streaming", {}),
    ("sc_sleep_bat", "Power", "Sleep", "Sleep on battery after", "choice", "sc", "system_idle_suspend_battery_sec",
     {"options": [[300, "5 minutes"], [600, "10 minutes"], [900, "15 minutes"], [1800, "30 minutes"], [3600, "1 hour"], [0, "Never"]]}),
    ("sc_sleep_ac", "Power", "Sleep", "Sleep when plugged in after", "choice", "sc", "system_idle_suspend_ac_sec",
     {"options": [[600, "10 minutes"], [1800, "30 minutes"], [3600, "1 hour"], [7200, "2 hours"], [0, "Never"]]}),
    ("sc_chargelimit_on", "Power", "Battery", "Limit charging (protects the battery)", "switch", "sc", "steamos_charge_limit_enabled", {}),
    ("sc_chargelimit", "Power", "Battery", "Charge up to", "slider", "sc", "steamos_charge_limit", {"min": 50, "max": 100, "step": 5, "unit": "%"}),
    ("sc_led", "Power", "Lights", "Status light brightness", "slider", "sc", "steamos_status_led_brightness", {"min": 0, "max": 100, "step": 5, "unit": "%"}),
    ("sc_ctrl_off", "Controls", "Controllers", "Turn other Steam controllers off after", "choice", "sc", "controller_power_off_timeout",
     {"options": [[5, "5 minutes"], [10, "10 minutes"], [15, "15 minutes"], [20, "20 minutes"], [30, "30 minutes"]]}),
    ("sc_ctrl_exit", "Controls", "Controllers", "Turn controllers off when leaving Steam", "switch", "sc", "turn_off_controller_on_exit", {}),
    ("sc_guide", "Controls", "Controllers", "Guide button opens Steam", "switch", "sc", "controller_guide_button_focus_steam", {}),
    ("sc_chord", "Controls", "Controllers", "Guide button shortcuts", "switch", "sc", "controller_enable_chord", {}),
    ("sc_xbox", "Controls", "Other controllers", "Xbox controller support", "switch", "sc", "controller_xbox_support", {}),
    ("sc_switch", "Controls", "Other controllers", "Switch Pro controller support", "switch", "sc", "controller_switch_support", {}),
    ("sc_generic", "Controls", "Other controllers", "Other gamepad support", "switch", "sc", "controller_generic_support", {}),
    ("sc_wifi_ps", "Connections", "Wi-Fi", "Wi-Fi power saving", "switch", "sc", "steamos_wifi_power_management_enabled", {}),
    ("sc_contrast", "Accessibility", "Seeing", "High contrast", "switch", "sc", "accessibility_high_contrast_mode", {}),
    ("sc_motion", "Accessibility", "Moving", "Reduce motion", "switch", "sc", "accessibility_reduce_motion", {}),
    ("sc_magnifier", "Accessibility", "Seeing", "Magnifier zoom", "slider", "sc", "steamos_magnifier_scale", {"min": 100, "max": 400, "step": 25, "unit": "%"}),
    ("sc_reader", "Accessibility", "Seeing", "Screen reader", "switch", "sc", "accessibility_screen_reader_enabled", {}),
    ("sc_smooth_scroll", "System", "Interface", "Smooth scrolling", "switch", "sc", "smooth_scroll_webviews", {}),
    # ---- Windows (BetterFrame)
    ("pins", "Windows", "Pin to Head", "Pin button on windows", "switch", "bf", None, {}),
    ("smooth", "Windows", "Pin to Head", "Smooth follow", "switch", "bf", None,
     {"desc": "The window glides after your head instead of being locked in place."}),
    # ---- more of SteamVR's own (only shown if this SteamVR has them)
    ("bounds_style", "Play Area", "Boundary", "Boundary style", "choice", "vr", "/settings/collisionBounds/CollisionBoundsStyle",
     {"options": [(0, "Beginner"), (1, "Intermediate"), (2, "Squares"), (3, "Advanced"), (4, "Nothing")]}),
    ("bounds_center", "Play Area", "Boundary", "Show the centre marker", "switch", "vr", "/settings/collisionBounds/CollisionBoundsCenterMarkerOn", {}),
    ("bounds_space", "Play Area", "Boundary", "Show the play space outline", "switch", "vr", "/settings/collisionBounds/CollisionBoundsPlaySpaceOn", {}),
    ("cam_on", "Play Area", "Camera", "Use the headset cameras", "switch", "vr", "/settings/camera/enableCamera", {}),
    ("cam_dash", "Play Area", "Camera", "See your room behind the menu", "switch", "vr", "/settings/camera/enableCameraInDashboard", {}),
    ("cam_bounds", "Play Area", "Camera", "See your room when near the boundary", "switch", "vr", "/settings/camera/enableCameraForCollisionBounds", {}),
    ("cam_room", "Play Area", "Camera", "Room view", "switch", "vr", "/settings/camera/enableCameraForRoomView", {}),
    # ---- BetterFrame Keyboard look and feel
    ("kb_theme", "Keyboard", "Look", "Themes", "choice", "pref", None,
     {"default": "steam", "options": [["steam", "Steam"], ["midnight", "Midnight"], ["slate", "Slate"],
                                      ["light", "Light"], ["ocean", "Ocean"], ["violet", "Violet"], ["forest", "Forest"],
                                      ["sunset", "Sunset"], ["rose", "Rose"], ["contrast", "Contrast"]]}),
    ("kb_backdrop", "Keyboard", "Look", "Backdrop behind the keys", "slider", "pref", None,
     {"default": 100, "min": 0, "max": 100, "step": 10, "unit": "%",
      "desc": "0% hides it. The backdrop button on the keyboard turns it on and off too"}),
    ("kb_bar", "Keyboard", "Look", "Top bar", "choice", "pref", None,
     {"default": "top", "options": [["top", "Above the keys"], ["bottom", "Below the keys"], ["off", "Off"]],
      "desc": "Where Undo, Copy, Paste, the layouts and the buttons go"}),
    ("kb_bottom", "Keyboard", "Look", "Bottom row", "choice", "pref", None,
     {"default": "default", "options": [["default", ".?123, Fn, Ctrl"], ["laptop", "Ctrl, Fn (like a laptop)"]],
      "desc": "The keys left of the space bar on the Minimal and Standard layouts"}),
    ("kb_tips", "Keyboard", "Look", "Button labels", "switch", "pref", None,
     {"default": True, "desc": "Shows what a top bar button does when you point at it"}),
    ("kb_ontop", "Keyboard", "Look", "Always on top", "switch", "pref", None,
     {"default": False, "desc": "Shows the keyboard in front of other windows"}),
    ("kb_aimfade", "Keyboard", "Look", "Fade when not aiming", "switch", "pref", None,
     {"default": True, "desc": "Unless both lasers point at the keyboard, it turns see-through and the lasers pass "
                               "through it to what's behind. The small button on its bottom edge turns this on and off too"}),
    ("kb_aimfade_op", "Keyboard", "Look", "How visible when faded", "slider", "pref", None,
     {"default": 25, "min": 5, "max": 100, "step": 5, "unit": "%"}),
    ("kb_lang", "Keyboard", "Typing", "Language", "choice", "pref", None,
     {"default": "en-US", "options": _lang_options(), "desc": "The keyboard's letters, word suggestions and voice typing"}),
    ("kb_fmt", "Keyboard", "Typing", "Key layout", "choice", "pref", None,
     {"default": "default", "options": [["default", "Your language's own"], ["qwerty", "QWERTY"], ["qwertz", "QWERTZ"],
                                        ["azerty", "AZERTY"], ["dvorak", "Dvorak"], ["colemak", "Colemak"],
                                        ["colemak-dh", "Colemak-DH"]],
      "desc": "Where the letters sit on the keyboard"}),
    ("kb_words", "Keyboard", "Typing", "Word suggestions", "switch", "pref", None,
     {"default": False, "desc": "Suggested words above the keys as you type"}),
    ("kb_preview", "Keyboard", "Typing", "Key preview", "switch", "pref", None,
     {"default": True, "desc": "Shows the letter you're pointing at just above the key"}),
    ("kb_hold", "Keyboard", "Typing", "Holding a key", "choice", "pref", None,
     {"default": "repeat", "options": [["repeat", "Repeats it"], ["shift", "Types its capital"]],
      "desc": "Repeat the letter, or type its capital (hold a for A, 1 for !)"}),
    ("kb_gamepad", "Keyboard", "Game controllers", "Type with", "choice", "pref", None,
     {"default": "pads", "options": [["pads", "Trackpads"], ["split", "Trackpads, split in half"],
                                     ["steam", "Steam's keyboard"], ["off", "Off"]],
      "desc": "Steam Controller and PS5 controller: each trackpad reaches every key, press it to type. Sticks and "
              "D-pad move between keys. Steam's keyboard works with any controller"}),
    ("kb_padpress", "Keyboard", "Game controllers", "Trackpad press", "choice", "pref", None,
     {"default": "light", "options": [["light", "Light"], ["normal", "Medium"], ["firm", "Firm"]],
      "desc": "How hard you press a Steam Controller trackpad to type a key"}),
    ("kb_padbuttons", "Keyboard", "Game controllers", "Face buttons", "switch", "pref", None,
     {"default": True, "desc": "A types, X Backspace (hold to keep deleting), Y Space, Menu Enter, B closes the "
                                "keyboard, left bumper Shift"}),
    ("kb_stream", "Keyboard", "Streamed games", "Type into games streamed from your PC", "choice", "pref", None,
     {"default": "steam", "options": [["steam", "Through Steam"], ["keys", "As key presses"]],
      "desc": "If letters don't show up in a streamed game, try As key presses"}),
    ("kb_sound", "Keyboard", "Sound and vibration", "Key sound", "choice", "pref", None,
     {"default": "deep", "options": [["deep", "Original"], ["light", "Light"], ["off", "Off"]],
      "desc": "The click when you press a key"}),
    ("kb_haptics", "Keyboard", "Sound and vibration", "Vibrate on each key", "switch", "pref", None,
     {"default": False, "desc": "Your controller gives a small vibration with each key you press"}),
        # ---- tracking extras: saved now, they take effect once these features arrive
    ("ctl_mode", "Tracking", "Control", "Control the menus with", "choice", "pref", None,
     {"default": "off", "options": [["off", "Controllers (as the Steam Frame comes)"], ["look_pinch", "Look and pinch"],
                                    ["look_hold", "Look and hold your look"], ["hand_point", "Point with your hand and pinch"],
                                    ["custom", "Custom (the switches below)"]],
      "desc": "Eyes and hands work with the SteamVR menu open and both controllers put down. Pick up a controller "
              "and it's back to normal"}),
    ("mover_on", "Play Area", "Move the play space", "Move the play space", "switch", "pref", None,
     {"default": False, "desc": "Tap a bumper, then press and hold it: the world follows your hand. Hold both to turn it "
                                "too. Never while a menu or the keyboard is open. Off puts your real play space back"}),
    ("mover_height", "Play Area", "Move the play space", "Keep my floor height", "switch", "pref", None,
     {"default": True, "desc": "Off: lift or lower the world by moving your hand up or down"}),
    ("mover_turn", "Play Area", "Move the play space", "Turn with both hands", "switch", "pref", None,
     {"default": True}),
    ("mover_huge", "Play Area", "Move the play space", "Hide the boundary while moved", "switch", "pref", None,
     {"default": True, "desc": "Stops your real boundary popping up in the moved world. It is also your warning before a "
                               "real wall: mind your room"}),
    ("mover_speed", "Play Area", "Move the play space", "Grab speed", "slider", "pref", None,
     {"default": 100, "min": 50, "max": 300, "step": 25, "unit": "%", "desc": "How far the world moves for each step your hand moves"}),
    ("mover_buzz", "Play Area", "Move the play space", "Buzz when grabbing", "switch", "pref", None,
     {"default": True}),
    ("hand_on", "Tracking", "Hands", "Hand tracking", "switch", "pref", None,
     {"default": False, "desc": "Test: follows your hands with the headset's cameras while SteamVR's menu is up and the controllers are put down"}),
    ("hand_ui", "Tracking", "Hands", "Pinch to click", "switch", "pref", None,
     {"default": True, "desc": "Controllers down, menu open: pinch thumb and index to click. With Look to select on, "
                               "you click what you look at; with it off, you point with your hand, like on a Quest"}),
    ("hand_switch", "Tracking", "Hands", "Switch to hands when controllers are put down", "switch", "pref", None,
     {"default": True, "desc": "With Hand tracking and Show your hands on: put the controllers down and your real hands appear"}),
    ("hand_color", "Tracking", "Hands", "Use the colour camera add-on in bright rooms", "switch", "pref", None,
     {"default": False, "desc": "Test: with an Arcturus Vision camera and its lens set up (bfhands.py colorcal). Its "
                                "pictures are only half there while the headset is worn, so this is off by default"}),
    ("hand_models", "Tracking", "Hands", "Show your hands", "switch", "pref", None,
     {"default": False, "desc": "Smooth hands while SteamVR's menu is up: on your controllers, or your real hands with hand tracking"}),
    ("gaze_ui", "Tracking", "Eyes", "Look to select in menus", "switch", "pref", None,
     {"default": False, "desc": "Test: the laser goes where you look in SteamVR's menus and windows while your controllers are put down. "
                                "Click with a pinch (hand tracking) or by looking a moment (hold time). Needs the pointer add-on"}),
    ("gaze_kb", "Tracking", "Eyes", "Type by looking at a key and pinching", "switch", "pref", None,
     {"default": True, "desc": "With Look to select on: the keyboard snaps your look to the nearest key, so you don't have to aim exactly"}),
    ("gaze_glow", "Tracking", "Eyes", "Highlight what you look at", "switch", "pref", None,
     {"default": False, "desc": "The key you look at on the keyboard lights up blue. Test: keyboard only for now"}),
    ("gaze_type", "Tracking", "Eyes", "Look at a key and press A to type it", "switch", "pref", None,
     {"default": False, "desc": "A or X on either controller types the key you're looking at. Test: keyboard only for now"}),
    ("gaze_dwell", "Tracking", "Eyes", "Click by looking (hold time)", "slider", "pref", None,
     {"default": 800, "min": 0, "max": 2000, "step": 100, "unit": " ms", "desc": "Look at something this long to click it (a key, or with Look to select, anything). 0 = off"}),
    ("trk_other", "Tracking", "Trackers", "Allow other trackers", "switch", "pref", None, {"default": False, "desc": "Body and object trackers from other makers. Not working yet"}),
    ("trk_show", "Tracking", "Trackers", "Show trackers in the menu", "switch", "pref", None, {"default": True, "desc": "Not working yet"}),
    ("trk_battery", "Tracking", "Trackers", "Low battery warnings", "switch", "pref", None, {"default": True, "desc": "Not working yet"}),
]
PREFS = os.path.expanduser("~/.config/betterframe-keyboard/prefs.json")


def prefs():
    try:
        with open(PREFS) as f:
            return json.load(f)
    except Exception:
        return {}
CATS = ["Display", "Sound", "Keyboard", "Windows", "Controls", "Tracking", "Play Area", "Games", "People", "Connections", "Power", "Accessibility", "System"]


def read_all():
    """Reads only: SteamVR's settings come from the plain list its settings page keeps (no SteamVR functions are
    called, they can upset its menu); Steam's two come from Steam's own settings calls."""
    out = {}
    vr = [x for x in S if x[5] == "vr"]
    url = dashpin.dashboard()
    if url:
        js = ("(() => { const m = window.VRSettingsState && VRSettingsState.settings; if (!m) return null; return {"
              + ", ".join("%s: m.get(%s)" % (json.dumps(x[0]), json.dumps(x[6])) for x in vr) + "}; })()")
        try:
            got = dashpin.run_js(url, js)
        except Exception as ex:
            got = "error: %s" % ex
        for x in vr:
            if isinstance(got, dict) and got.get(x[0]) is not None:
                v = got[x[0]]
                out[x[0]] = {"v": round(v * x[7]["scale"]) if "scale" in x[7] and isinstance(v, (int, float)) else v}
            else:
                out[x[0]] = {"err": "not available" if isinstance(got, dict) or got is None else str(got)[:120]}
    else:
        for x in vr:
            out[x[0]] = {"err": "SteamVR menu not reachable"}
    sc = [x for x in S if x[5] in ("sc", "sf")]
    url = dashpin.steam_page()
    if url and sc:
        js = ("(() => { const s = window.settingsStore; if (!s) return null; const c = s.m_ClientSettings || {}, f = s.m_FriendSettings || {};"
              " return {" + ", ".join("%s: %s[%s]" % (json.dumps(x[0]), "c" if x[5] == "sc" else "f", json.dumps(x[6])) for x in sc) + "}; })()")
        try:
            got = dashpin.run_js(url, js)
        except Exception as ex:
            got = "error: %s" % ex
        for x in sc:
            if isinstance(got, dict) and got.get(x[0]) is not None:
                v = got[x[0]]
                out[x[0]] = {"v": round(v * x[7]["scale"]) if "scale" in x[7] and isinstance(v, (int, float)) else v}
            else:
                out[x[0]] = {"err": "not available"}
    else:
        for x in sc:
            out[x[0]] = {"err": "Steam not reachable"}
    st = [x for x in S if x[5] == "steam"]
    for x in st:
        try:
            v = dashpin.run_js(url, "(async () => { try { return await %s; } catch (e) { return null; } })()" % x[6], wait=True) if url else None
            out[x[0]] = {"v": v} if v is not None else {"err": "not available"}
        except Exception as ex:
            out[x[0]] = {"err": str(ex)}
    try:
        import bfmode
        pf = bfmode.apply(prefs())        # (the switches show what "Control the menus with" makes them)
    except ImportError:
        pf = prefs()                      # (the keyboard on its own)
    for x in S:
        if x[5] == "pref":
            out[x[0]] = {"v": pf.get(x[0], x[7].get("default"))}
    out["pins"] = {"v": os.path.exists(dashpin.ON) and not os.path.exists(dashpin.OFF)}
    out["smooth"] = {"v": os.path.exists(dashpin.SMOOTH)}
    return out


def write(sid, value):
    item = next((x for x in S if x[0] == sid), None)
    if not item:
        return "unknown setting"
    _, cat, sec, label, kind, where, path, ex = item
    if kind == "switch":
        value = bool(value)
    elif kind == "slider":
        value = max(ex["min"], min(ex["max"], float(value))) / ex.get("scale", 1)
    elif kind == "choice":
        allowed = [o[0] for o in ex["options"]]
        value = next((o for o in allowed if str(o) == str(value).split(".")[0] or str(o) == str(value)), None)
        if value is None:
            return "not an allowed value"
    else:
        return "read only"
    if where == "pref":
        pf = prefs()
        if sid in ("gaze_ui", "hand_on", "hand_ui", "gaze_dwell") and pf.get("ctl_mode", "off") != "custom":
            # flipping one of the separate switches: keep what's working now, and let the switches decide from here
            import bfmode
            pf = bfmode.apply(pf)
            pf["ctl_mode"] = "custom"
        pf[sid] = value
        os.makedirs(os.path.dirname(PREFS), exist_ok=True)
        with open(PREFS + ".tmp", "w") as f:
            json.dump(pf, f)
        os.replace(PREFS + ".tmp", PREFS)
        return "ok"
    if where == "bf":
        sys.argv = ["dashpin.py", "on" if value else "off"] if sid == "pins" else ["dashpin.py", "smooth", "on" if value else "off"]
        try:
            dashpin.main()
        except Exception as e:
            return str(e)
        return "ok"
    if where in ("sc", "sf"):
        url = dashpin.steam_page()
        if not url:
            return "Steam not reachable"
        setters = ["SetClientSetting", "SetSetting"] if where == "sc" else ["SetFriendSetting", "SetFriendsSetting"]
        res = dashpin.run_js(url, "(() => { const s = window.settingsStore; if (!s) return 'no store';"
                             " for (const f of %s) if (typeof s[f] === 'function') { try { s[f](%s, %s); return 'ok'; } catch (e) { return 'error: ' + e; } }"
                             " return 'Steam has no way to change this one from here yet'; })()" % (json.dumps(setters), json.dumps(path), json.dumps(value)))
    else:
        url = dashpin.dashboard()
        if not url:
            return "SteamVR menu not reachable"
        # the one call SteamVR's own settings page makes to change a setting
        res = dashpin.run_js(url, "(() => { try { VRSettingsState.SetSettingsValue(%s, %s); return 'ok'; } catch (e) { return 'error: ' + e; } })()"
                             % (json.dumps(path), json.dumps(value)))
    if res != "ok":
        return res
    import time
    time.sleep(0.6)  # then check it really changed
    now = read_all().get(sid, {}).get("v")
    want = round(value * ex["scale"]) if "scale" in ex and isinstance(value, (int, float)) and kind == "slider" else value
    if now == want or (isinstance(now, (int, float)) and isinstance(want, (int, float)) and abs(now - want) <= 1):
        return "ok"
    return "didn't stick (still %s)%s" % (now, " - it may apply after SteamVR restarts" if where == "vr" else "")


def definitions():
    return [{"id": x[0], "cat": x[1], "sec": x[2], "label": x[3], "kind": x[4],
             "min": x[7].get("min"), "max": x[7].get("max"), "step": x[7].get("step", 1), "unit": x[7].get("unit", ""), "div": x[7].get("div"),
             "options": x[7].get("options")} for x in S]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/settings"):
            return self.send(200, {"cats": CATS, "defs": definitions(), "values": read_all()})
        if self.path in ("/", "/settings"):
            with open(os.path.join(HERE, "settings.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/api/set"):
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(min(n, 10000)) or b"{}")
            return self.send(200, {"result": write(str(req.get("id")), req.get("value"))})
        return self.send(404, {"error": "not found"})


STEAM_DUMP = r"""
(() => {
  const out = {};
  const prim = v => v === null || ['string', 'number', 'boolean'].includes(typeof v);
  const walk = (o, path, depth) => {
    if (!o || typeof o !== 'object' || depth > 3) return;
    let keys = [];
    try { keys = Object.keys(o); } catch (e) { return; }
    if (keys.length > 400) keys = keys.slice(0, 400);
    for (const k of keys) {
      let v; try { v = o[k]; } catch (e) { continue; }
      if (typeof v === 'function') continue;
      if (prim(v)) out[path + k] = v;
      else if (Array.isArray(v)) { if (v.length < 30 && v.every(prim)) out[path + k] = JSON.stringify(v); }
      else if (v && typeof v === 'object' && !(v instanceof Map) && !(v instanceof Set) && !(v.nodeType)) walk(v, path + k + '.', depth + 1);
    }
  };
  const st = window.settingsStore;
  if (!st) return JSON.stringify({error: 'no settingsStore'});
  walk(st, '', 0);
  return JSON.stringify(out);
})()
"""


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "steamdump":  # looks only: every value in Steam's settings store
        url = dashpin.steam_page()
        got = dashpin.run_js(url, STEAM_DUMP) if url else "Steam's UI isn't reachable"
        path = os.path.expanduser("~/Downloads/steam-settings.txt")
        with open(path, "w") as f:
            try:
                for k, v in sorted(json.loads(got).items()):
                    f.write("%s = %s\n" % (k, json.dumps(v)))
            except Exception:
                f.write(str(got) + "\n")
        print("Saved to", path)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        vals = read_all()
        for x in S:
            print("%-12s %-10s %-34s %s" % (x[1], x[0], x[3], json.dumps(vals.get(x[0]))))
        return
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print("BetterFrame Settings: open http://localhost:%d in a browser (Ctrl+C to stop)" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


# (the keyboard on its own: only its own settings)
S = [x for x in S if x[0] in ("kb_theme", "kb_backdrop", "kb_bar", "kb_bottom", "kb_tips", "kb_gamepad", "kb_padbuttons", "kb_padpress", "kb_ontop", "kb_aimfade", "kb_aimfade_op", "kb_stream", "kb_hold", "kb_lang", "kb_preview", "kb_words", "kb_fmt", "kb_sound", "kb_haptics")]
