package com.ohmymeme.app

import android.view.KeyEvent
import kotlin.system.exitProcess

class PasteUserService : IPasteUserService.Stub() {

    override fun destroy() {
        exitProcess(0)
    }

    override fun paste(): Boolean {
        return try {
            Runtime.getRuntime().exec(
                arrayOf("input", "keyevent", KeyEvent.KEYCODE_PASTE.toString())
            ).waitFor() == 0
        } catch (_: Exception) {
            false
        }
    }
}
