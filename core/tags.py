def create_tag_type(bv, name, icon="", color=""):
    existing = bv.get_tag_type(name)
    if existing:
        return existing
    return bv.create_tag_type(name, icon, color)


def tag_item(bv, addr, tag_type_name, data=""):
    tag_type = bv.get_tag_type(tag_type_name)
    if not tag_type:
        return
    bv.add_tag(tag_type, addr, data)
