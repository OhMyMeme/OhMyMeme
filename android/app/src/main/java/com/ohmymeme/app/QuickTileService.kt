package com.ohmymeme.app

import android.content.Intent
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/**
 * 通知栏控制中心快捷按钮：点击打开主界面。
 * 用户需在系统「快捷设置」编辑面板手动添加本磁贴；
 * Android 13+（API 33）可在设置页调用 [android.service.quicksettings.TileService.requestAddTileService] 引导添加。
 */
class QuickTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        updateTile()
    }

    override fun onClick() {
        if (isLocked) {
            unlockAndRun { launchApp() }
        } else {
            launchApp()
        }
    }

    private fun launchApp() {
        try {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
            )
        } catch (e: Exception) {
            android.util.Log.w(TAG, "launch failed: $e")
        }
    }

    private fun updateTile() {
        val tile = qsTile ?: return
        tile.state = Tile.STATE_ACTIVE
        tile.updateTile()
    }

    private companion object {
        const val TAG = "OhMyMeme/QuickTile"
    }
}
