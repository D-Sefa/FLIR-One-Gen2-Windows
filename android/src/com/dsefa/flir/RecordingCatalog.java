package com.dsefa.flir;

import java.io.File;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.*;

/** Local calendar dates derived from capture timestamps, never from file names. */
public final class RecordingCatalog {
    private RecordingCatalog(){}
    public static List<String> dates(File[] files) {
        SortedSet<String> dates=new TreeSet<>(Collections.reverseOrder());
        SimpleDateFormat format=new SimpleDateFormat("yyyy-MM-dd",Locale.US);
        if(files!=null)for(File file:files) {
            if(file==null||!file.isFile())continue;
            try(RecordingIndex index=new RecordingIndex(file)){dates.add(format.format(new Date(index.firstTimestamp())));}
            catch(IOException ignored){/* Incomplete or unavailable recordings are not playable. */}
        }
        return new ArrayList<>(dates);
    }
    public static List<File> onDate(File[] files,String date) {
        final Map<File,Long> times=new HashMap<>();
        SimpleDateFormat format=new SimpleDateFormat("yyyy-MM-dd",Locale.US);
        if(files!=null&&date!=null)for(File file:files) {
            if(file==null||!file.isFile())continue;
            try(RecordingIndex index=new RecordingIndex(file)) {
                long time=index.firstTimestamp();
                if(date.equals(format.format(new Date(time))))times.put(file,time);
            }catch(IOException ignored){}
        }
        List<File> result=new ArrayList<>(times.keySet());
        Collections.sort(result,(a,b)->{int order=Long.compare(times.get(b),times.get(a));return order!=0?order:a.getAbsolutePath().compareTo(b.getAbsolutePath());});
        return result;
    }
}
