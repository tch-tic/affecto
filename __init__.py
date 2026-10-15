def classFactory(iface):
    from .plugin import AffectationPlugin
    return AffectationPlugin(iface)
