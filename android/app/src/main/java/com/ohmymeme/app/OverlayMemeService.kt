package com.ohmymeme.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.RemoteException
import android.provider.Settings
import android.view.KeyEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.abs

class OverlayMemeService : Service() {

    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private lateinit var windowManager: WindowManager
    private var buttonView: View? = null
    private var panelView: View? = null
    private var buttonParams: WindowManager.LayoutParams? = null
    private var panelParams: WindowManager.LayoutParams? = null
    private var lastQuery = ""
    private var shizukuPermissionListener: rikka.shizuku.Shizuku.OnRequestPermissionResultListener? = null

    companion object {
        const val PASTE_ROUTE_MANUAL = "manual"
        const val PASTE_ROUTE_ACCESSIBILITY = "accessibility"
        const val PASTE_ROUTE_SHIZUKU = "shizuku"
        const val PASTE_ROUTE_ROOT = "root"
        const val PASTE_ROUTE_SHARE = "share"

        private const val ACTION_SHOW = "com.ohmymeme.app.action.SHOW_OVERLAY"
        private const val ACTION_STOP = "com.ohmymeme.app.action.STOP_OVERLAY"
        private const val CHANNEL_ID = "overlay_meme_search"
        private const val NOTIFICATION_ID = 41
        private const val SHIZUKU_REQUEST_CODE = 4101
        private val ACCESSIBILITY_COMPONENT = ComponentName(
            "com.ohmymeme.app",
            "com.ohmymeme.app.MemePasteAccessibilityService"
        )

        fun requestEnable(context: Context) {
            if (!Settings.canDrawOverlays(context)) {
                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:${context.packageName}")
                )
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
                return
            }
            ConfigStore.set(context, "overlay_enabled", true)
            ConfigStore.save(context)
            ContextCompat.startForegroundService(
                context,
                Intent(context, OverlayMemeService::class.java).setAction(ACTION_SHOW)
            )
        }

        fun stop(context: Context) {
            ConfigStore.set(context, "overlay_enabled", false)
            ConfigStore.save(context)
            context.stopService(Intent(context, OverlayMemeService::class.java))
        }

        fun isAccessibilityEnabled(context: Context): Boolean {
            val enabled = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: return false
            return enabled.split(':').any { value ->
                ComponentName.unflattenFromString(value) == ACCESSIBILITY_COMPONENT
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        shizukuPermissionListener = rikka.shizuku.Shizuku.OnRequestPermissionResultListener { requestCode, result ->
            if (requestCode == SHIZUKU_REQUEST_CODE) {
                if (result == PackageManager.PERMISSION_GRANTED) runShizukuPaste()
                else notifyPasteResult(getString(R.string.overlay_shizuku_denied))
            }
        }
        rikka.shizuku.Shizuku.addRequestPermissionResultListener(shizukuPermissionListener!!)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stop(this)
            return START_NOT_STICKY
        }
        startAsForeground()
        if (Settings.canDrawOverlays(this)) showButton()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        shizukuPermissionListener?.let { rikka.shizuku.Shizuku.removeRequestPermissionResultListener(it) }
        closePanel()
        removeButton()
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun startAsForeground() {
        val stopIntent = PendingIntent.getService(
            this,
            0,
            Intent(this, OverlayMemeService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_qs_tile)
            .setContentTitle(getString(R.string.overlay_notification_title))
            .setContentText(getString(R.string.overlay_notification_text))
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .addAction(0, getString(R.string.overlay_stop), stopIntent)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.overlay_notification_channel),
            NotificationManager.IMPORTANCE_LOW
        )
        channel.setShowBadge(false)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun showButton() {
        if (buttonView != null) return
        val size = dp(58)
        val icon = ImageView(this).apply {
            setImageResource(R.drawable.ic_qs_tile)
            setColorFilter(Color.WHITE)
            contentDescription = getString(R.string.overlay_button_description)
            background = circleDrawable(getColor(R.color.accent), dp(29))
            elevation = dp(8).toFloat()
            setPadding(dp(15), dp(15), dp(15), dp(15))
        }
        val params = baseParams(size, size, WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE).apply {
            val savedX = ConfigStore.getInt(this@OverlayMemeService, "overlay_button_x", -1)
            val savedY = ConfigStore.getInt(this@OverlayMemeService, "overlay_button_y", -1)
            x = if (savedX >= 0) savedX else resources.displayMetrics.widthPixels - size - dp(18)
            y = if (savedY >= 0) savedY else dp(180)
        }
        setupButtonTouch(icon, params)
        buttonView = icon
        buttonParams = params
        windowManager.addView(icon, params)
    }

    private fun setupButtonTouch(view: View, params: WindowManager.LayoutParams) {
        view.setOnTouchListener(object : View.OnTouchListener {
            private var startX = 0
            private var startY = 0
            private var startRawX = 0f
            private var startRawY = 0f
            private var dragging = false

            override fun onTouch(v: View, event: MotionEvent): Boolean {
                when (event.action) {
                    MotionEvent.ACTION_DOWN -> {
                        startX = params.x
                        startY = params.y
                        startRawX = event.rawX
                        startRawY = event.rawY
                        dragging = false
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx = (event.rawX - startRawX).toInt()
                        val dy = (event.rawY - startRawY).toInt()
                        dragging = dragging || abs(dx) > dp(6) || abs(dy) > dp(6)
                        if (dragging) {
                            params.x = (startX + dx).coerceIn(0, resources.displayMetrics.widthPixels - dp(48))
                            params.y = (startY + dy).coerceAtLeast(0)
                            windowManager.updateViewLayout(v, params)
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        if (dragging) {
                            ConfigStore.set(this@OverlayMemeService, "overlay_button_x", params.x)
                            ConfigStore.set(this@OverlayMemeService, "overlay_button_y", params.y)
                            ConfigStore.save(this@OverlayMemeService)
                        } else {
                            showPanel()
                        }
                        return true
                    }
                }
                return false
            }
        })
    }

    private fun showPanel() {
        if (panelView != null) return
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedDrawable(getColor(R.color.surface), dp(14))
            elevation = dp(12).toFloat()
            setPadding(dp(10), dp(10), dp(10), dp(10))
        }
        val header = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            orientation = LinearLayout.HORIZONTAL
        }
        val title = TextView(this).apply {
            text = getString(R.string.overlay_panel_title)
            setTextColor(getColor(R.color.fg))
            textSize = 14f
            setTypeface(typeface, 1)
        }
        val close = TextView(this).apply {
            text = "×"
            gravity = Gravity.CENTER
            textSize = 25f
            setTextColor(getColor(R.color.fg_secondary))
            contentDescription = getString(R.string.close)
            setOnClickListener { closePanel() }
        }
        header.addView(title, LinearLayout.LayoutParams(0, dp(34), 1f))
        header.addView(close, LinearLayout.LayoutParams(dp(34), dp(34)))

        val search = EditText(this).apply {
            background = roundedDrawable(getColor(R.color.surface_2), dp(9))
            hint = getString(R.string.search_hint)
            setHintTextColor(getColor(R.color.muted))
            setTextColor(getColor(R.color.fg))
            textSize = 13f
            setSingleLine(true)
            setPadding(dp(12), 0, dp(12), 0)
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
        }
        val recycler = RecyclerView(this).apply {
            layoutManager = GridLayoutManager(this@OverlayMemeService, 4)
            overScrollMode = View.OVER_SCROLL_NEVER
            setPadding(dp(2), dp(7), dp(2), 0)
            clipToPadding = false
        }
        val hint = TextView(this).apply {
            text = getString(R.string.overlay_usage_hint)
            setTextColor(getColor(R.color.muted))
            textSize = 11f
            setPadding(dp(2), dp(7), dp(2), 0)
        }
        root.addView(header)
        root.addView(search, LinearLayout.LayoutParams(-1, dp(40)))
        root.addView(recycler, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(hint)

        search.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                loadMemes(recycler, s?.toString()?.trim().orEmpty())
            }
        })
        val width = dp(324)
        val height = dp(440)
        val params = baseParams(width, height, 0).apply {
            val button = buttonParams
            x = (button?.x ?: dp(18)).coerceIn(0, resources.displayMetrics.widthPixels - width)
            y = (button?.y ?: dp(180)).coerceAtLeast(0)
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }
        panelView = root
        panelParams = params
        windowManager.addView(root, params)
        loadMemes(recycler, "")
        search.requestFocus()
    }

    private fun loadMemes(recycler: RecyclerView, query: String) {
        lastQuery = query
        executor.execute {
            val memes = if (query.isEmpty()) {
                MemeDb.get(this).getRecent(80).ifEmpty { MemeDb.get(this).getAll(limit = 80) }
            } else {
                MemeDb.get(this).search(keyword = query, limit = 80)
            }
            recycler.post {
                if (query != lastQuery || panelView == null) return@post
                recycler.adapter = MemeGridAdapter(this, memes, false, showMenu = false).apply {
                    onItemClick = { _, meme -> copyMeme(meme) }
                    onDragStart = { view, meme -> startGlobalDrag(view, meme) }
                }
            }
        }
    }

    private fun copyMeme(meme: Meme) {
        executor.execute {
            val file = materializeFile(meme) ?: return@execute
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
            val label = meme.originalName.ifEmpty { meme.filename }
            val clip = ClipData.newUri(contentResolver, label, uri)
            val clipboard = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(clip)
            MemeDb.get(this).recordUse(meme.id)
            panelView?.post { showPasteChoices(uri, meme.mimeType.ifEmpty { "image/*" }) }
        }
    }

    private fun showPasteChoices(uri: Uri, mimeType: String) {
        val route = ConfigStore.getString(this, "overlay_paste_route", PASTE_ROUTE_MANUAL)
        if (route != PASTE_ROUTE_MANUAL) {
            runPasteRoute(route, uri, mimeType)
            return
        }
        val choices = mutableListOf(
            getString(R.string.overlay_paste_manual),
            getString(R.string.overlay_paste_accessibility)
        )
        val actions = mutableListOf<() -> Unit>(
            { notifyPasteResult(getString(R.string.overlay_copied_manual)) },
            { pasteWithAccessibility() }
        )
        choices.add(getString(R.string.overlay_paste_shizuku))
        actions.add { pasteWithShizuku() }
        choices.add(getString(R.string.overlay_paste_root))
        actions.add { pasteWithRoot() }
        choices.add(getString(R.string.overlay_paste_share))
        actions.add { shareCopiedMeme(uri, mimeType) }
        android.app.AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
            .setTitle(getString(R.string.overlay_paste_title))
            .setMessage(getString(R.string.overlay_paste_note))
            .setItems(choices.toTypedArray()) { _, which -> actions[which].invoke() }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun runPasteRoute(route: String, uri: Uri, mimeType: String) {
        when (route) {
            PASTE_ROUTE_ACCESSIBILITY -> pasteWithAccessibility()
            PASTE_ROUTE_SHIZUKU -> pasteWithShizuku()
            PASTE_ROUTE_ROOT -> pasteWithRoot()
            PASTE_ROUTE_SHARE -> shareCopiedMeme(uri, mimeType)
            else -> notifyPasteResult(getString(R.string.overlay_copied_manual))
        }
    }

    private fun pasteWithAccessibility() {
        val service = MemePasteAccessibilityService.instance
        if (service == null || !isAccessibilityEnabled()) {
            startActivity(
                Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            notifyPasteResult(getString(R.string.overlay_accessibility_required))
            return
        }
        if (service.pasteFocusedNode()) {
            notifyPasteResult(getString(R.string.overlay_paste_attempted))
        } else {
            notifyPasteResult(getString(R.string.overlay_paste_unavailable))
        }
    }

    private fun pasteWithShizuku() {
        if (!isShizukuAvailable()) {
            notifyPasteResult(getString(R.string.overlay_shizuku_required))
            return
        }
        try {
            if (rikka.shizuku.Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                rikka.shizuku.Shizuku.requestPermission(SHIZUKU_REQUEST_CODE)
                notifyPasteResult(getString(R.string.overlay_shizuku_authorize))
                return
            }
            runShizukuPaste()
        } catch (_: Exception) {
            notifyPasteResult(getString(R.string.overlay_paste_unavailable))
        }
    }

    private fun runShizukuPaste() {
        executor.execute {
            val args = rikka.shizuku.Shizuku.UserServiceArgs(
                ComponentName(this, PasteUserService::class.java)
            ).processNameSuffix("meme-paste").daemon(false).version(1)
            var connection: ServiceConnection? = null
            connection = object : ServiceConnection {
                override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
                    val userService = IPasteUserService.Stub.asInterface(service)
                    val pasted = try {
                        userService.paste()
                    } catch (_: RemoteException) {
                        false
                    }
                    rikka.shizuku.Shizuku.unbindUserService(args, this, true)
                    notifyPasteResult(
                        getString(
                            if (pasted) R.string.overlay_paste_attempted
                            else R.string.overlay_paste_unavailable
                        )
                    )
                }

                override fun onServiceDisconnected(name: ComponentName?) {
                }
            }
            try {
                rikka.shizuku.Shizuku.bindUserService(args, connection)
            } catch (_: Exception) {
                notifyPasteResult(getString(R.string.overlay_paste_unavailable))
            }
        }
    }

    private fun pasteWithRoot() {
        executor.execute {
            try {
                val process = Runtime.getRuntime().exec(
                    arrayOf("su", "-c", "input keyevent ${KeyEvent.KEYCODE_PASTE}")
                )
                val dispatched = process.waitFor() == 0
                notifyPasteResult(
                    getString(if (dispatched) R.string.overlay_paste_attempted else R.string.overlay_paste_unavailable)
                )
            } catch (_: Exception) {
                notifyPasteResult(getString(R.string.overlay_paste_unavailable))
            }
        }
    }

    private fun isShizukuAvailable(): Boolean {
        return try {
            rikka.shizuku.Shizuku.pingBinder()
        } catch (_: Exception) {
            false
        }
    }

    private fun isRootBackendAvailable(): Boolean {
        return try {
            isShizukuAvailable() && rikka.shizuku.Shizuku.getUid() == 0
        } catch (_: Exception) {
            false
        }
    }

    private fun isAccessibilityEnabled(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
            ?: return false
        return enabled.split(':').any { value ->
            ComponentName.unflattenFromString(value) == ACCESSIBILITY_COMPONENT
        }
    }

    private fun shareCopiedMeme(uri: Uri, mimeType: String) {
        val share = Intent(Intent.ACTION_SEND).apply {
            type = mimeType
            putExtra(Intent.EXTRA_STREAM, uri)
            clipData = ClipData.newUri(contentResolver, getString(R.string.app_name), uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        startActivity(Intent.createChooser(share, getString(R.string.share_title))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun notifyPasteResult(message: String) {
        Handler(Looper.getMainLooper()).post {
            android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_SHORT).show()
        }
    }

    private fun startGlobalDrag(itemView: View, meme: Meme) {
        executor.execute {
            val file = materializeFile(meme) ?: return@execute
            itemView.post {
                val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
                val label = meme.originalName.ifEmpty { meme.filename.substringBeforeLast('.') }
                val shadow = itemView.findViewById<View>(R.id.img_meme) ?: itemView
                val started = itemView.startDragAndDrop(
                    ClipData.newUri(contentResolver, label, uri),
                    View.DragShadowBuilder(shadow),
                    meme,
                    View.DRAG_FLAG_GLOBAL or View.DRAG_FLAG_GLOBAL_URI_READ
                )
                if (started) MemeDb.get(this).recordUse(meme.id)
            }
        }
    }

    private fun materializeFile(meme: Meme): File? {
        return try {
            val stor = Thumbnailer.findMemeFile(this, meme.filename) ?: return null
            val ext = meme.filename.substringAfterLast('.', "img")
            File(cacheDir, "overlay_${meme.id}_${System.nanoTime()}.$ext").also { stor.copyTo(it) }
        } catch (e: Exception) {
            android.util.Log.w("OhMyMeme/Overlay", "materialize failed: $e")
            null
        }
    }

    private fun closePanel() {
        panelView?.let {
            try {
                windowManager.removeView(it)
            } catch (_: Exception) {
            }
        }
        panelView = null
        panelParams = null
    }

    private fun removeButton() {
        buttonView?.let {
            try {
                windowManager.removeView(it)
            } catch (_: Exception) {
            }
        }
        buttonView = null
        buttonParams = null
    }

    private fun baseParams(width: Int, height: Int, flags: Int): WindowManager.LayoutParams {
        return WindowManager.LayoutParams(
            width,
            height,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            flags or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
        }
    }

    private fun circleDrawable(color: Int, radius: Int): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(color)
            cornerRadius = radius.toFloat()
        }
    }

    private fun roundedDrawable(color: Int, radius: Int): GradientDrawable {
        return GradientDrawable().apply {
            setColor(color)
            cornerRadius = radius.toFloat()
            setStroke(dp(1), getColor(R.color.border))
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
