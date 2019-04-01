import traceback


class ImageInfo(object):
    CAPS ='caps'

    def __init__(self, docker, label_match, label_prefix, image_prefix='', exclude_labels=None):
        self.docker = docker
        self.image_prefix = image_prefix
        self.label_match = label_match
        self.label_prefix = label_prefix
        self.exclude_labels = exclude_labels or []

    def _load_info(self, labels, include_all=False):
        props = {}
        caps = []
        for n, v in labels.items():
            label_prop = n.split(self.label_prefix)
            if len(label_prop) != 2:
                continue

            name = label_prop[1]

            if not include_all and name in self.exclude_labels:
                continue

            props[name] = v

            if name.startswith(self.CAPS):
                caps.append(name.split('.', 1)[1])

        if caps:
            props[self.CAPS] = ', '.join(caps)

        return props

    def _get_primary_id(self, tags):
        if not tags:
            return None

        primary_tag = None
        for tag in tags:
            if not tag:
                continue

            if tag.endswith(':latest'):
                tag = tag.replace(':latest', '')

            if not tag.startswith(self.image_prefix):
                continue

            # pick the longest tag as primary tag
            if not primary_tag or len(tag) > len(primary_tag):
                primary_tag = tag

        if primary_tag:
            return primary_tag[len(self.image_prefix):]
        else:
            return None

    def list_images(self, params=None):
        filters = {"dangling": False}

        label_filters = [self.label_match]

        id_ = None
        include_all = False

        if params:
            for k, v in params.items():
                if k == 'id':
                    id_ = v
                    include_all = True
                    continue

                if k == 'include_all':
                    include_all = bool(v)
                    continue

                label_filters.append(self.label_prefix + k + '=' + v)

        filters["label"] = label_filters

        image_results = {}

        try:
            if id_:
                images = [self.docker.images.get(self.image_prefix + id_)]
            else:
                images = self.docker.images.list(filters=filters)

            for image in images:
                id_ = self._get_primary_id(image.tags)
                if not id_:
                    continue

                props = self._load_info(image.labels, include_all=include_all)
                props['id'] = id_

                image_results[id_] = props

        except Exception:
            traceback.print_exc()

        return image_results


