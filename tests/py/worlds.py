# Fake AB worlds shared by the script tests. Shapes follow the live AB 2.9
# probes of 2026-10-17 on an AC500 V3 PM5032 consumer project.
import os
import tempfile
import scriptengine as se

# Real files under a per-test temp root: the scripts check os.path.exists()
# and list the project folder (build cache files).
ROOT = os.environ.get('FAKE_ROOT') or tempfile.mkdtemp(prefix='fake-ab-')
PROJECT = os.path.join(ROOT, 'proj', 'MPLUS_IO.project')
WEB_LIB = os.path.join(ROOT, 'repo', 'AC500-V3-utilities-web.library')
UTIL_LIB = os.path.join(ROOT, 'repo', 'Util.compiled-library-v3')
for _p in (PROJECT, WEB_LIB, UTIL_LIB):
    if not os.path.isdir(os.path.dirname(_p)):
        os.makedirs(os.path.dirname(_p))
    if not os.path.exists(_p):
        open(_p, 'wb').close()

WEB_PARAM_DECL = (
    "// sizes of the server, overridable in the Library Manager of the project\n"
    "VAR_GLOBAL CONSTANT\n"
    "\tgc_uiSlots    : UINT  := 3;        // connections per listener\n"
    "\tgc_udiBodyMax : UDINT := 4096;     // dynamic body (JSON) buffer per slot\n"
    "\tgc_udiPageMax : UDINT := 262144;   // page file buffer (one per server)\n"
    "END_VAR\n"
)


def ac500_project(released=False, web_overrides=None, util_overrides=None):
    """Project with an Application LM (user placeholders, system placeholders,
    managed refs) and a project-root LM, a task configuration, an App/Visu
    folder holding an ImagePool."""
    app_lm = se.LibMan('Library Manager', [
        se.Ref('#LogiQ', placeholder=True, resolution='AC500-V3-LogiQ, 0.0.2 (ABB)'),
        se.Ref('#MProtocol', placeholder=True, resolution='MProtocol-library, 1.0.0 (ABB)'),
        se.Ref('#Util', placeholder=True, resolution='Util, 3.5.21.0 (System)',
               overrides=util_overrides if util_overrides is not None else {'IBLOCKSIZE': '22800'}),
        se.Ref('#Standard', placeholder=True, system=True, resolution='Standard, 3.5.18.0 (System)'),
        se.Ref('AC500-V3-utilities-web, 1.0.0 (ABB)', namespace='UtilsWeb',
               overrides=web_overrides or {},
               managed_lib=se.ManagedLib('AC500-V3-utilities-web, 1.0.0 (ABB)', WEB_LIB)),
        se.Ref('AC500-V3-utilities-ip, 1.0.2 (ABB)', namespace='UtilsIP'),
    ])
    root_lm = se.LibMan('Library Manager', [
        se.Ref('#System_VisuElems', placeholder=True, system=True),
        se.Ref('#CmpSchedule', placeholder=True, resolution='CmpSchedule, 3.5.17.0 (System)'),
    ])
    tc = se.TaskConfig([se.Task('MainTask')])
    visu = se.Node('Visu', [se.Node('ImagePool', type_guid='bb0b9044-714e-4614-ad3e-33cbdf34d16b',
                                    is_imagepool=True)],
                   type_guid='738bea1e-99bb-4f04-90bb-a7a567e74e3a', is_folder=True)
    prg = se.Pou('WEB_PRG', 'PROGRAM WEB_PRG\nVAR\nEND_VAR')
    app_folder = se.Node('App', [visu, prg], type_guid='738bea1e-99bb-4f04-90bb-a7a567e74e3a', is_folder=True)
    app = se.Node('Application', [tc, app_lm, app_folder],
                  type_guid='639b491f-5557-464c-af91-1471bac9f549', is_application=True)
    plc = se.Node('PLC_AC500_V3', [se.Node('Plc Logic', [app], type_guid='40b404f9-e5dc-42c6-907f-c89f4a517386')],
                  type_guid='225bfe47-7336-4dbc-9419-4105a7c831fa', is_device=True)
    proj = se.Project(PROJECT, [plc, root_lm], released=released)
    proj.active_application = app
    se.projects.primary = proj
    se.projects.all = [proj]
    se.projects.openable[PROJECT] = proj

    # Library sources reachable through the library manager.
    web_src = se.Project(WEB_LIB, [se.Pou('Param', WEB_PARAM_DECL, 'ffbfa93a-b94d-45fc-a329-229860183b1d')])
    web_src.primary = False
    se.projects.openable[WEB_LIB] = web_src
    se.librarymanager.by_display['Util, 3.5.21.0 (System)'] = se.ManagedLib('Util, 3.5.21.0 (System)', UTIL_LIB)
    return {'project': proj, 'app_lm': app_lm, 'root_lm': root_lm, 'tc': tc, 'web_src': web_src}


def ref(lm, display):
    return lm.references[display]
