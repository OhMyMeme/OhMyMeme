package com.ohmymeme.app

import android.content.Context
import android.graphics.ImageDecoder
import android.graphics.drawable.AnimatedImageDrawable
import android.graphics.drawable.Drawable
import android.view.DragEvent
import android.view.MotionEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MemeGridAdapter(
    private val context: Context,
    items: List<Meme>,
    private val canOrder: Boolean,
    private val showMenu: Boolean = true
) : RecyclerView.Adapter<MemeGridAdapter.MemeViewHolder>() {

    private val items: MutableList<Meme> = items.toMutableList()
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()

    var onItemClick: ((View, Meme) -> Unit)? = null
    var onMenuClick: ((View, Meme) -> Unit)? = null
    var onDragStart: ((View, Meme) -> Unit)? = null
    var onDragFailed: ((View, Meme) -> Unit)? = null
    var onReorderStart: ((MemeViewHolder) -> Unit)? = null

    fun move(from: Int, to: Int) {
        if (from == to) return
        val item = items.removeAt(from)
        items.add(to, item)
        notifyItemMoved(from, to)
    }

    fun currentIds(): List<Long> = items.map { it.id }

    class MemeViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): MemeViewHolder {
        val itemView = LayoutInflater.from(parent.context).inflate(R.layout.item_meme, parent, false)
        return MemeViewHolder(itemView)
    }

    override fun onBindViewHolder(holder: MemeViewHolder, position: Int) {
        val meme = items[position]
        val img = holder.itemView.findViewById<ImageView>(R.id.img_meme)
        val name = holder.itemView.findViewById<TextView>(R.id.tv_meme_name)
        val badge = holder.itemView.findViewById<TextView>(R.id.tv_meme_badge)
        val dragHandle = holder.itemView.findViewById<ImageView>(R.id.btn_drag_handle)
        val menuButton = holder.itemView.findViewById<View>(R.id.btn_meme_menu)
        (img.drawable as? AnimatedImageDrawable)?.stop()
        img.setImageResource(R.drawable.ic_photo)
        img.setColorFilter(context.getColor(R.color.muted))
        img.tag = meme.id
        name.text = meme.originalName.ifEmpty { meme.filename.substringBeforeLast('.') }
        holder.itemView.setOnClickListener {
            onItemClick?.invoke(it, meme)
        }
        holder.itemView.setOnLongClickListener {
            onDragStart?.invoke(it, meme)
            true
        }
        holder.itemView.setOnDragListener { v, e ->
            if (e.action == DragEvent.ACTION_DRAG_ENDED && !e.result) {
                onDragFailed?.invoke(v, meme)
            }
            true
        }
        menuButton.visibility = if (showMenu) View.VISIBLE else View.GONE
        menuButton.setOnClickListener {
            onMenuClick?.invoke(it, meme)
        }
        menuButton.setOnLongClickListener { showMenu }
        dragHandle.visibility = if (canOrder) View.VISIBLE else View.GONE
        dragHandle.setOnTouchListener(null)
        if (canOrder) {
            dragHandle.setOnTouchListener { _, event ->
                if (event.action != MotionEvent.ACTION_DOWN) return@setOnTouchListener true
                if (holder.bindingAdapterPosition == RecyclerView.NO_POSITION) {
                    return@setOnTouchListener false
                }
                onReorderStart?.invoke(holder)
                true
            }
        }
        executor.execute {
            val animated = isAnimatedFile(meme)
            val isGif = meme.mimeType.endsWith("gif") || meme.filename.lowercase().endsWith(".gif")
            img.post {
                if (img.tag == meme.id) {
                    badge.text = when {
                        meme.fromStego == 1 -> context.getString(R.string.badge_stego)
                        animated -> if (isGif) context.getString(R.string.badge_gif) else context.getString(R.string.badge_webp)
                        else -> ""
                    }
                    badge.visibility = if (meme.fromStego == 1 || animated) View.VISIBLE else View.GONE
                }
            }
            val autoPlay = ConfigStore.getBoolean(context, "auto_play_gif", true)
            if (animated && autoPlay) {
                loadAnimated(img, meme)
            } else {
                loadThumb(img, meme)
            }
        }
    }

    private fun isAnimatedFile(meme: Meme): Boolean {
        if (meme.mimeType.endsWith("gif") || meme.filename.lowercase().endsWith(".gif")) return true
        if (meme.filename.lowercase().endsWith(".webp")) {
            val f = StoragePaths.cacheDir(context).child(meme.filename)
            if (!f.exists) return false
            return FileUtils.isAnimatedFile(f)
        }
        return false
    }

    private fun loadAnimated(img: ImageView, meme: Meme) {
        val file = Thumbnailer.findMemeFile(context, meme.filename) ?: return
        val drawable = decodeAnimated(file)
        if (drawable == null) {
            loadThumb(img, meme)
            return
        }
        if (img.tag != meme.id) return
        img.post {
            if (img.tag == meme.id) {
                img.setColorFilter(null)
                img.setImageTintList(null)
                img.setImageDrawable(drawable)
                (drawable as? AnimatedImageDrawable)?.start()
            }
        }
    }

    private fun decodeAnimated(stor: StorFile): Drawable? {
        return try {
            val uri = stor.uri
            val source = if (uri != null) {
                ImageDecoder.createSource(context.contentResolver, uri)
            } else {
                ImageDecoder.createSource(stor.realFile!!)
            }
            ImageDecoder.decodeDrawable(source) { decoder, info, _ ->
                decoder.setTargetSampleSize(sampleSize(info.size.width, info.size.height, 300))
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun loadThumb(img: ImageView, meme: Meme) {
        val bitmap = Thumbnailer.getThumbBitmap(context, meme.id, meme.filename)
        if (bitmap != null && img.tag == meme.id) {
            img.post {
                if (img.tag == meme.id) {
                    img.setColorFilter(null)
                    img.setImageTintList(null)
                    img.setImageBitmap(bitmap)
                }
            }
        }
    }

    private fun sampleSize(w: Int, h: Int, target: Int): Int {
        var sample = 1
        while (w / sample > target * 2 || h / sample > target * 2) {
            sample *= 2
        }
        return sample
    }

    override fun getItemCount() = items.size
}
