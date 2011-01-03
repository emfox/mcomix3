"""archive_extractor.py - Archive extraction class."""

import sys
import os
import zipfile
import tarfile
import threading
import gtk
import process
import archive_tools
import constants

can_handle_pdf = False

#try:
#    import poppler
#    import cairo
#    can_handle_pdf = True
#except Exception:
#    can_handle_pdf = False
can_handle_pdf = False

_rar_exec = None

class Extractor:

    """Extractor is a threaded class for extracting different archive formats.

    The Extractor can be loaded with paths to archives (currently ZIP, tar,
    or RAR archives) and a path to a destination directory. Once an archive
    has been set it is possible to filter out the files to be extracted and
    set the order in which they should be extracted. The extraction can
    then be started in a new thread in which files are extracted one by one,
    and a signal is sent on a condition after each extraction, so that it is
    possible for other threads to wait on specific files to be ready.

    Note: Support for gzip/bzip2 compressed tar archives is limited, see
    set_files() for more info.
    """

    def __init__(self):
        self._setupped = False

    def setup(self, src, dst, type=None):
        """Setup the extractor with archive <src> and destination dir <dst>.
        Return a threading.Condition related to the is_ready() method, or
        None if the format of <src> isn't supported.
        """
        self._src = src
        self._dst = dst
        
        if type != None:
            self._type = type
        else:
            self._type = archive_tools.archive_mime_type(src)
            
        self._files = []
        self._extracted = {}
        self._stop = False
        self._extract_thread = None
        self._condition = threading.Condition()

        if self._type == constants.ZIP:
            self._zfile = zipfile.ZipFile(src, 'r')
            self._files = self._zfile.namelist()
            
        elif self._type in (constants.TAR, constants.GZIP, constants.BZIP2):
            self._tfile = tarfile.open(src, 'r')
            self._files = self._tfile.getnames()
            
        elif self._type == constants.RAR:
            global _rar_exec
            
            if _rar_exec is None:
                _rar_exec = archive_tools._get_rar_exec()
                
                if _rar_exec is None:
                    print _('! Could not find RAR file extractor.')
                    
                    dialog = gtk.MessageDialog(None, 0, gtk.MESSAGE_WARNING,
                        gtk.BUTTONS_CLOSE,
                        _("Could not find RAR file extractor!"))
                        
                    dialog.format_secondary_markup(
                        _("You need either the <i>rar</i> or the <i>unrar</i> program installed in order to read RAR (.cbr) files."))
                        
                    dialog.run()
                    dialog.destroy()
                    
                    return None
                    
            proc = process.Process([_rar_exec, 'vb', '--', src])
            fd = proc.spawn()
            self._files = [name.rstrip(os.linesep) for name in fd.readlines()]
            fd.close()
            proc.wait()
            
        elif self._type == constants.PDF:
            global can_handle_pdf
            
            #if can_handle_pdf:

            #    self._source_pdf = poppler.document_new_from_file ('file://' + self._src, None)
            #    self._num_of_pages = self._source_pdf.get_n_pages()
    
            #    self._files = [self._dst + str(n) + '.png' for n in range(0, self._num_of_pages)]
                
            #else:
            #    return None

        else:
            print _('! Non-supported archive format:'), src
            return None

        self._setupped = True

        return self._condition

    def get_files(self):
        """Return a list of names of all the files the extractor is currently
        set for extracting. After a call to setup() this is by default all
        files found in the archive. The paths in the list are relative to
        the archive root and are not absolute for the files once extracted.
        """
        return self._files[:]

    def set_files(self, files):
        """Set the files that the extractor should extract from the archive in
        the order of extraction. Normally one would get the list of all files
        in the archive using get_files(), then filter and/or permute this
        list before sending it back using set_files().

        Note: Random access on gzip or bzip2 compressed tar archives is
        no good idea. These formats are supported *only* for backwards
        compability. They are fine formats for some purposes, but should
        not be used for scanned comic books. So, we cheat and ignore the
        ordering applied with this method on such archives.
        """
        if self._type in (constants.GZIP, constants.BZIP2):
            self._files = [x for x in self._files if x in files]
        else:
            self._files = files

    def is_ready(self, name):
        """Return True if the file <name> in the extractor's file list
        (as set by set_files()) is fully extracted.
        """
        return self._extracted.get(name, False)

    def get_mime_type(self):
        """Return the mime type name of the extractor's current archive."""
        return self._type

    def stop(self):
        """Signal the extractor to stop extracting and kill the extracting
        thread. Blocks until the extracting thread has terminated.
        """
        self._stop = True

        if self._setupped:
            self._extract_thread.join()
            self.setupped = False

    def extract(self):
        """Start extracting the files in the file list one by one using a
        new thread. Every time a new file is extracted a notify() will be
        signalled on the Condition that was returned by setup().
        """
        self._extract_thread = threading.Thread(target=self._thread_extract)
        self._extract_thread.setDaemon(False)
        self._extract_thread.start()

    def close(self):
        """Close any open file objects, need only be called manually if the
        extract() method isn't called.
        """
        if self._type == constants.ZIP:
            self._zfile.close()
        elif self._type in (constants.TAR, constants.GZIP, constants.BZIP2):
            self._tfile.close()

    def _thread_extract(self):
        """Extract the files in the file list one by one."""
        
        if self._type != constants.PDF:
            for name in self._files:
                self._extract_file(name)
        else:
            for n in range(0, self._num_of_pages):
                self._extract_file(n)
                
        self.close()

    def _extract_file(self, name):
        """Extract the file named <name> to the destination directory,
        mark the file as "ready", then signal a notify() on the Condition
        returned by setup().
        """
        if self._stop:
            self.close()
            sys.exit(0)

        try:
            if self._type == constants.ZIP:
                dst_path = os.path.join(self._dst, name)

                if not os.path.exists(os.path.dirname(dst_path)):
                    os.makedirs(os.path.dirname(dst_path))

                new = open(dst_path, 'wb')
                new.write(self._zfile.read(name))
                new.close()

            elif self._type in (constants.TAR, constants.GZIP, constants.BZIP2):

                if os.path.normpath(os.path.join(self._dst, name)).startswith(
                  self._dst):
                    self._tfile.extract(name, self._dst)

                else:
                    print _('! Non-local tar member:'), name, '\n'

            elif self._type == constants.RAR:

                if _rar_exec is not None:
                    proc = process.Process([_rar_exec, 'x', '-kb', '-p-',
                        '-o-', '-inul', '--', self._src, name, self._dst])
                    proc.spawn()
                    proc.wait()
                else:
                    print _('! Could not find RAR file extractor.')
            
            elif self._type == constants.PDF:
                pass
                #page = self._source_pdf.get_page(n)
                #width, height = page.get_size()

        except Exception:
            # Better to ignore any failed extractions (e.g. from a corrupt
            # archive) than to crash here and leave the main thread in a
            # possible infinite block. Damaged or missing files *should* be
            # handled gracefully by the main program anyway.
            pass
            
        self._condition.acquire()
        self._extracted[name] = True
        self._condition.notify()
        self._condition.release()