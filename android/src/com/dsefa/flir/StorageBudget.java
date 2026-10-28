package com.dsefa.flir;
import java.io.*;
import java.util.*;

/** Only the application's own completed RAW/image segments are deletion candidates. */
public final class StorageBudget {
    private static final Map<File,StorageBudget> sharedBudgets=new HashMap<>();
    public static synchronized StorageBudget shared(File directory,long limit)throws IOException{
        File path=directory.getCanonicalFile();StorageBudget b=sharedBudgets.get(path);
        if(b==null){b=new StorageBudget(path,limit);sharedBudgets.put(path,b);}else b.setLimit(limit);return b;}
    private final File directory;private long limit;
    private final Map<File,Long> active=new HashMap<>();
    private final Map<File,Integer> pins=new HashMap<>();
    public StorageBudget(File directory,long limit)throws IOException{this.directory=directory.getCanonicalFile();this.limit=limit;}
    public static long limitFromMb(long mb){return Math.max(100,Math.min(10000,mb))*1000000L;}
    public synchronized void setLimit(long bytes){limit=bytes;}
    private File checked(File file)throws IOException{File f=file.getCanonicalFile();
        if(!directory.equals(f.getParentFile())||!owned(f))throw new IOException("Unsafe recording path");return f;}
    private static boolean owned(File file){String name=file.getName();return name.startsWith("FLIR-")&&(name.endsWith(".f1raw")||name.endsWith(".f1clip"));}
    public synchronized void open(File file)throws IOException{File f=checked(file);active.put(f,0L);}
    public synchronized void pin(File file)throws IOException{File f=checked(file);if(!f.isFile()||active.containsKey(f))throw new IOException("Recording unavailable or still active");pins.put(f,pins.getOrDefault(f,0)+1);}
    public synchronized void restorePin(File file)throws IOException{File f=checked(file);if(!pins.containsKey(f))pin(f);}
    public synchronized void unpin(File file){try{File f=checked(file);int n=pins.getOrDefault(f,0);if(n<=1)pins.remove(f);else pins.put(f,n-1);}catch(IOException ignored){}}
    public synchronized void reserve(File file,long bytes)throws IOException{File f=checked(file);
        if(!active.containsKey(f))throw new IOException("Recording not active");
        File[] listed=directory.listFiles();List<File> candidates=new ArrayList<>();long total=0;
        if(listed!=null)for(File item:listed){if(!item.isFile()||!owned(item))continue;
            File safe=checked(item);if(!active.containsKey(safe)){total+=safe.length();if(!pins.containsKey(safe))candidates.add(safe);}}
        for(long size:active.values())total+=size;
        candidates.sort(Comparator.comparingLong(File::lastModified).thenComparing(File::getName));
        for(File old:candidates){if(total+bytes<=limit)break;long size=old.length();if(!old.delete())throw new IOException("Cannot remove oldest recording");total-=size;}
        if(bytes<0||total+bytes>limit)throw new IOException("Recording storage limit reached; recording stopped");
        if(directory.getUsableSpace()<bytes+1048576)throw new IOException("Phone storage is nearly full; recording stopped");
        active.put(f,active.get(f)+bytes);
    }
    public synchronized void release(File file){try{active.remove(file.getCanonicalFile());}catch(IOException ignored){}}
    public synchronized boolean isActive(File file){try{return active.containsKey(file.getCanonicalFile());}catch(IOException e){return true;}}
}
