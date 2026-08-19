package com.ohmymeme.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OrderingEligibilityTest {
    @Test
    fun allowsGlobalOrderingWithAtLeastTwoItems() {
        assertTrue(canOrderCards("", null, 2))
    }

    @Test
    fun allowsPositiveCollectionOrderingWithAtLeastTwoItems() {
        assertTrue(canOrderCards("", 12L, 2))
    }

    @Test
    fun rejectsNonEmptySearch() {
        assertFalse(canOrderCards("cat", null, 2))
    }

    @Test
    fun rejectsVirtualCollections() {
        assertFalse(canOrderCards("", -2L, 2))
        assertFalse(canOrderCards("", -3L, 2))
        assertFalse(canOrderCards("", -4L, 2))
    }

    @Test
    fun rejectsFewerThanTwoItems() {
        assertFalse(canOrderCards("", null, 1))
        assertFalse(canOrderCards("", null, 0))
    }
}
