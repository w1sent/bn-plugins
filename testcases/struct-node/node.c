/* Test binary for ai/suggest-structs.
 *
 * Exercises all three suggest-structs triggers:
 *   1. alloc_node()'s `p` is a heap pointer accessed at several fixed
 *      offsets (classic "struct never declared, just offset math") --
 *      trigger 1 (variable access-pattern analysis).
 *   2. g_config is a fixed-size global blob accessed via raw offsets, with
 *      no declared type -- usable both as a manual byte-range selection
 *      (trigger 2) and, since BN gives it a name like `g_config` (not the
 *      data_/byte_/etc. auto-generated prefix), NOT auto-picked up by
 *      trigger 3's batch sweep -- see run.py for why that's deliberate.
 *   3. g_scratch has no symbol, so BN names it `data_<addr>` -- this is
 *      what trigger 3's batch sweep is meant to find.
 */
#include <stdlib.h>
#include <string.h>

/* Deliberately no struct declaration -- suggest-structs should infer this
 * shape from the offset accesses below: field 0 = int id, field 4 = int
 * name_len, field 8 = char name[16] (24 bytes), field 24 = void* next. */
void *alloc_node(int id, const char *name) {
    unsigned char *p = malloc(32);
    if (!p)
        return NULL;
    *(int *)(p + 0) = id;
    *(int *)(p + 4) = (int)strlen(name);
    memcpy(p + 8, name, strlen(name) + 1);
    *(void **)(p + 24) = NULL;
    return p;
}

void link_nodes(void *first, void *second) {
    *(void **)((unsigned char *)first + 24) = second;
}

int node_id(void *node) {
    return *(int *)((unsigned char *)node + 0);
}

/* Named global blob: offset 0 = uint32_t magic, offset 4 = uint16_t
 * version, offset 6 = uint16_t flags, offset 8..15 = char tag[8]. */
unsigned char g_config[16];

void init_config(void) {
    *(unsigned int *)(g_config + 0) = 0xCAFEBABEu;
    *(unsigned short *)(g_config + 4) = 1;
    *(unsigned short *)(g_config + 6) = 0;
    memcpy(g_config + 8, "nodepool", 8);
}

/* This blob's symbol is stripped by build.py after compiling (see the
 * objcopy step there), so BN sees no name for it and falls back to
 * data_<addr> -- exactly the auto-generated-name pattern trigger 3's batch
 * sweep looks for. offset 0 = int count, offset 4 = int capacity. */
static unsigned char g_scratch[8];

void init_scratch(void) {
    *(int *)(g_scratch + 0) = 0;
    *(int *)(g_scratch + 4) = 64;
}

int main(void) {
    init_config();
    init_scratch();
    void *a = alloc_node(1, "alpha");
    void *b = alloc_node(2, "beta");
    link_nodes(a, b);
    int id = node_id(a);
    free(a);
    free(b);
    return id;
}
