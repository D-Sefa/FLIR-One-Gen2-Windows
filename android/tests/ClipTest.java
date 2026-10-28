package com.dsefa.flir;

import java.io.*;
import java.nio.file.*;
import java.util.*;

public final class ClipTest {
    public static void main(String[] args)throws Exception {
        File dir=Files.createTempDirectory("flir-clip-").toFile();
        try {
            randomAccess(dir);rejectCorruption(dir);recorderRateAndOwnership(dir);segmentationAndBudget(dir);
            System.out.println("PASS image clip seek / corruption / 1fps / ownership / segments / storage protection");
        } finally {for(File file:dir.listFiles())file.delete();dir.delete();}
    }
    // Catches variable-size record offset errors and nearest-time rounding errors.
    static void randomAccess(File dir)throws Exception {
        File file=new File(dir,"roundtrip.f1clip");
        try(ImageClip.Writer writer=new ImageClip.Writer(new FileOutputStream(file))) {
            writer.write(100,new byte[]{1,2});writer.write(1200,new byte[]{3,4,5});writer.write(4000,new byte[]{6});
        }
        try(ImageClip.Reader reader=new ImageClip.Reader(file)) {
            check(reader.count()==3&&reader.firstTimestamp()==100&&reader.lastTimestamp()==4000,"clip metadata");
            ImageClip.Sample last=reader.read(2);check(last.timestamp==4000&&Arrays.equals(last.jpeg,new byte[]{6}),"variable-size final frame");
            ImageClip.Sample first=reader.read(0);check(Arrays.equals(first.jpeg,new byte[]{1,2}),"backward seek");
            check(reader.timestamp(1)==1200,"timestamp lookup");
            check(reader.nearest(650)==0&&reader.nearest(651)==1&&reader.nearest(3000)==2,"nearest frame / earlier tie");
            check(reader.nearest(Long.MIN_VALUE)==0&&reader.nearest(Long.MAX_VALUE)==2,"seek clamps");
            try {reader.read(3);throw new AssertionError("Out of bounds accepted");}catch(IndexOutOfBoundsException expected){}
        }
    }
    // Catches accepting incomplete files and unbounded JPEG allocations from corrupt lengths.
    static void rejectCorruption(File dir)throws Exception {
        File file=new File(dir,"corrupt.f1clip");
        try(DataOutputStream out=new DataOutputStream(new FileOutputStream(file))){out.writeInt(0x46314A31);}reject(file);
        for(int length:new int[]{0,-1,2097153,2}) {
            try(DataOutputStream out=new DataOutputStream(new FileOutputStream(file))){out.writeInt(0x46314A31);out.writeLong(100);out.writeInt(length);out.writeByte(1);}reject(file);
        }
        try(DataOutputStream out=new DataOutputStream(new FileOutputStream(file))){out.writeInt(0);out.writeLong(100);out.writeInt(1);out.writeByte(1);}reject(file);
        try(ImageClip.Writer writer=new ImageClip.Writer(new FileOutputStream(file))){writer.write(200,new byte[]{1});
            try {writer.write(100,new byte[]{2});throw new AssertionError("Writer accepted timestamp reversal");}catch(IOException expected){}
            try {writer.write(300,new byte[0]);throw new AssertionError("Writer accepted empty JPEG");}catch(IOException expected){}
        }
    }
    // Catches accepting >1fps, rate limiting rejected frames, retaining mutable buffers or losing accepted frames on close.
    static void recorderRateAndOwnership(File dir)throws Exception {
        File file=new File(dir,"FLIR-rate.f1clip");List<String> errors=Collections.synchronizedList(new ArrayList<String>());
        ImageRecorder recorder=new ImageRecorder(file,errors::add,null,16*1024*1024);
        byte[] jpeg={7,8,9};check(recorder.offer(jpeg,100),"first frame accepted");jpeg[0]=99;
        check(!recorder.offer(jpeg,1099),"sub-second frame refused");
        check(recorder.offer(jpeg,1100),"one second boundary accepted");
        check(!recorder.offer(jpeg,1000),"backwards source time refused");
        recorder.close();check(recorder.awaitComplete(3000)&&recorder.complete(),"writer drains on close");
        check(!recorder.offer(jpeg,9999),"closed recorder refuses frame");check(errors.isEmpty(),"unexpected recording failure "+errors);
        try(ImageClip.Reader reader=new ImageClip.Reader(file)){check(reader.count()==2,"accepted frame count");check(reader.read(0).jpeg[0]==7,"accepted bytes copied");check(reader.read(1).jpeg[0]==99,"second buffer snapshot");}
        try {new ImageRecorder(file,errors::add,null,1000);throw new AssertionError("Existing clip overwritten");}catch(IOException expected){}
        try(ImageClip.Reader reader=new ImageClip.Reader(file)){check(reader.count()==2,"existing file preserved");}
    }
    // Catches oversized segments, unprotected active clips, and pruning the wrong extension.
    static void segmentationAndBudget(File dir)throws Exception {
        StorageBudget budget=new StorageBudget(dir,10000);List<String> errors=Collections.synchronizedList(new ArrayList<String>());
        File file=new File(dir,"FLIR-segment.f1clip");ImageRecorder recorder=new ImageRecorder(file,errors::add,budget,40);
        check(budget.isActive(file),"first segment protected before return");
        check(recorder.offer(new byte[10],0),"segment first frame accepted");check(recorder.offer(new byte[10],1000),"segment next frame accepted");
        recorder.close();check(recorder.awaitComplete(3000),"segment writer finished");check(errors.isEmpty(),"segment error "+errors);
        File second=new File(dir,"FLIR-segment_part-0001.f1clip");
        check(file.isFile()&&second.isFile()&&file.length()==26&&second.length()==26,"correct clip rotation");
        check(!budget.isActive(file)&&!budget.isActive(second),"segment ownership released");
        try(ImageClip.Reader reader=new ImageClip.Reader(second)){check(reader.count()==1&&reader.read(0).timestamp==1000,"new segment contains next frame");}
    }
    static void reject(File file)throws Exception {try(ImageClip.Reader reader=new ImageClip.Reader(file)){throw new AssertionError("Corrupt clip accepted");}catch(IOException expected){}}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
