package com.ohmymeme.app

data class Meme(
    val id: Long,
    val filename: String,
    val fileHash: String,
    val originalName: String,
    val width: Int,
    val height: Int,
    val fileSize: Long,
    val mimeType: String,
    val sortOrder: Int,
    val stegoOfHash: String?,
    val fromStego: Int,
    val aiDescription: String,
    val aiOcrText: String,
    val createdAt: String,
    val updatedAt: String
)
