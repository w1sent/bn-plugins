def create_tag_type(bv, name, icon=""):
    existing = bv.get_tag_type(name)
    if existing:
        return existing
    return bv.create_tag_type(name, icon)


def tag_item(bv, addr, tag_type_name, data=""):
    bv.add_tag(addr, tag_type_name, data)
