package com.ohmymeme.app

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class ChipAdapter<T>(
    private val items: List<T>,
    private val activeItems: Set<T>,
    private val label: (T) -> String
) : RecyclerView.Adapter<ChipAdapter.ChipViewHolder>() {

    var onItemClick: ((T) -> Unit)? = null
    var onItemLongClick: ((View, T) -> Unit)? = null

    class ChipViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ChipViewHolder {
        val itemView = LayoutInflater.from(parent.context).inflate(R.layout.item_collection, parent, false)
        return ChipViewHolder(itemView)
    }

    override fun onBindViewHolder(holder: ChipViewHolder, position: Int) {
        val item = items[position]
        val text = label(item)
        val active = activeItems.contains(item)
        val chip = holder.itemView.findViewById<TextView>(R.id.tv_collection_chip)
        chip.text = text
        chip.setTextColor(holder.itemView.context.getColor(if (active) R.color.accent else R.color.muted))
        chip.setBackgroundResource(
            if (active) R.drawable.bg_collection_chip_active else R.drawable.bg_collection_chip
        )
        holder.itemView.setOnClickListener { onItemClick?.invoke(item) }
        holder.itemView.setOnLongClickListener {
            onItemLongClick?.invoke(holder.itemView, item)
            true
        }
    }

    override fun getItemCount() = items.size
}
