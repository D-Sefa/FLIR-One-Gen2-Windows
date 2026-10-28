package com.dsefa.flir;
import java.io.*;
import java.nio.file.*;
public class RecorderTest {
    public static void main(String[] args)throws Exception {
        Path folder=Files.createTempDirectory("flir-recorder-test");File existing=folder.resolve("existing.f1raw").toFile();
        Files.write(existing.toPath(),new byte[]{1,2,3});boolean refused=false;RawRecorder old=null;
        try{old=new RawRecorder(existing,s->{});}catch(Exception e){refused=true;}finally{if(old!=null)old.close();}
        if(!refused)throw new AssertionError("Recorder must never truncate an existing archive");
        if(Files.size(existing.toPath())!=3)throw new AssertionError("Existing archive changed");
        File fresh=folder.resolve("fresh.f1raw").toFile();RawRecorder writer=new RawRecorder(fresh,s->{throw new AssertionError(s);});
        int[] raw=new int[19200];raw[9]=12345;int accepted=0;
        for(int i=0;i<50;i++)if(writer.offer(raw,i))accepted++;
        writer.close();if(!writer.awaitComplete(3000)||!writer.complete())throw new AssertionError("Writer did not finalize");
        if(writer.offer(raw,999))throw new AssertionError("Stopped recorder accepted new data");
        int count=0;try(RawArchive.Reader reader=new RawArchive.Reader(new FileInputStream(fresh))){RawArchive.Sample sample;
            while((sample=reader.next())!=null){if(sample.raw[9]!=12345)throw new AssertionError("RAW changed");count++;}}
        if(count!=accepted)throw new AssertionError("Finalization lost queued samples: "+count+"/"+accepted);
        File ringDir=Files.createTempDirectory("flir-ring-test").toFile();
        StorageBudget budget=new StorageBudget(ringDir,100000);
        RawRecorder ring=new RawRecorder(new File(ringDir,"FLIR-ring.f1raw"),s->{throw new AssertionError(s);},budget,80000);
        for(int i=0;i<6;i++)ring.offer(raw,i);ring.close();
        if(!ring.awaitComplete(3000))throw new AssertionError("Ring recording did not stop");
        long bytes=0;int records=0;for(File f:ringDir.listFiles()){
            bytes+=f.length();try(RawArchive.Reader r=new RawArchive.Reader(new FileInputStream(f))){while(r.next()!=null)records++;}}
        if(bytes>100000||records!=2)throw new AssertionError("Recording failed to rotate/prune while preserving newest complete frames: "+bytes+"/"+records);
        System.out.println("PASS recorder exclusive file / finalization / "+count+" queued samples");
    }
}
