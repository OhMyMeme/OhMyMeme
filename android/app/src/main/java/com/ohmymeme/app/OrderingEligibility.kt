package com.ohmymeme.app

fun canOrderCards(keyword: String, collectionId: Long?, itemCount: Int): Boolean =
    keyword.isEmpty() && (collectionId == null || collectionId > 0L) && itemCount >= 2
